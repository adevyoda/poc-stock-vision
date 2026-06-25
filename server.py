"""
SAP Stock Vision

POC local:
- cadastro de materiais em SQLite;
- dashboard em tempo real;
- camera/foto no navegador enviando frame para YOLO;
- atualizacao de estoque mock SAP MM ou OData real quando SAP_MODE=real.
"""

import base64
import json
import os
import queue
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

try:
    from sap_config import SAP_MODE, sap_post, testar_conexao
except ImportError:
    SAP_MODE = "mock"

    def sap_post(path, payload):
        return {"mock": True, "path": path, "payload": payload}

    def testar_conexao():
        return True


app = Flask(__name__, static_folder="dashboard", static_url_path="")
CORS(app)

DB_PATH = Path(os.getenv("STOCK_DB_PATH", "stock_vision.db"))
WAREHOUSE_DEFAULT = os.getenv("WAREHOUSE_DEFAULT", "ALMOX-01")
SAP_STOCK_ODATA_PATH = os.getenv(
    "SAP_STOCK_ODATA_PATH",
    "/sap/opu/odata4/sap/zpoc_stock_vision/srvd/sap/zpoc_stock_vision/0001/StockVision",
)

DEFAULT_MATERIALS = [
    ("bottle", "Garrafa", "MAT-001", "UN", 5),
    ("cup", "Copo", "MAT-002", "UN", 10),
    ("cell phone", "Celular", "MAT-003", "UN", 2),
    ("book", "Livro", "MAT-004", "UN", 3),
    ("scissors", "Tesoura", "MAT-005", "UN", 2),
    ("keyboard", "Teclado", "MAT-006", "UN", 1),
    ("mouse", "Mouse", "MAT-007", "UN", 1),
    ("chair", "Cadeira", "MAT-008", "UN", 1),
]

clientes_sse = []
clientes_lock = threading.Lock()
db_lock = threading.Lock()
model_lock = threading.Lock()
yolo_model = None

ultima_leitura = {
    "fonte": "aguardando camera ou imagem",
    "local": WAREHOUSE_DEFAULT,
    "deteccoes": {},
    "timestamp": None,
}


def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db_lock, db() as con:
        con.execute(
            """
            create table if not exists materials (
              yolo_class text primary key,
              descricao text not null,
              sap_matnr text not null,
              unidade text not null default 'UN',
              minimo integer not null default 0,
              qtd integer not null default 0,
              active integer not null default 1
            )
            """
        )
        con.execute(
            """
            create table if not exists history (
              id integer primary key autoincrement,
              documento text not null,
              local text not null,
              itens integer not null,
              hora text not null,
              created_at text not null
            )
            """
        )
        for material in DEFAULT_MATERIALS:
            con.execute(
                """
                insert or ignore into materials
                  (yolo_class, descricao, sap_matnr, unidade, minimo, qtd, active)
                values (?, ?, ?, ?, ?, 0, 1)
                """,
                material,
            )


def rows_to_materials(rows):
    return {
        row["yolo_class"]: {
            "descricao": row["descricao"],
            "sap_matnr": row["sap_matnr"],
            "qtd": int(row["qtd"]),
            "unidade": row["unidade"],
            "minimo": int(row["minimo"]),
            "active": bool(row["active"]),
        }
        for row in rows
    }


def get_active_material_rows(con):
    return con.execute(
        "select * from materials where active = 1 order by descricao collate nocase"
    ).fetchall()


def build_estado():
    with db_lock, db() as con:
        material_rows = get_active_material_rows(con)
        materiais = rows_to_materials(material_rows)
        historico = [
            dict(row)
            for row in con.execute(
                "select documento, local, itens, hora from history order by id desc limit 10"
            ).fetchall()
        ]

    alertas = []
    for classe, mat in materiais.items():
        if mat["minimo"] > 0 and mat["qtd"] < mat["minimo"]:
            alertas.append(
                {
                    "tipo": "REPOSICAO_NECESSARIA",
                    "classe": classe,
                    "matnr": mat["sap_matnr"],
                    "descricao": mat["descricao"],
                    "qtd_atual": mat["qtd"],
                    "qtd_minima": mat["minimo"],
                    "hora": datetime.now().strftime("%H:%M:%S"),
                }
            )

    return {
        "materiais": materiais,
        "historico": historico,
        "ultima_leitura": ultima_leitura,
        "ultima_atualizacao": datetime.now().isoformat(),
        "total_itens": sum(mat["qtd"] for mat in materiais.values()),
        "alertas_reposicao": alertas[:8],
        "sap_mode": SAP_MODE,
    }


def notificar_clientes():
    dados = json.dumps(build_estado(), ensure_ascii=False, default=str)
    msg = f"data: {dados}\n\n"
    with clientes_lock:
        vivos = []
        for q in clientes_sse:
            try:
                q.put(msg)
                vivos.append(q)
            except Exception:
                pass
        clientes_sse[:] = vivos


def publicar_no_sap_real(classe, mat, quantidade, local):
    payload = {
        "MaterialNumber": mat["sap_matnr"],
        "Warehouse": local[:10] or WAREHOUSE_DEFAULT,
        "Quantity": int(quantidade),
        "Unit": mat["unidade"],
        "DetectedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "Source": "camera_01",
    }
    return sap_post(SAP_STOCK_ODATA_PATH, payload)


def atualizar_snapshot(deteccoes, local, fonte, timestamp=None, snapshot_completo=True):
    global ultima_leitura

    doc_sap = f"INV{int(time.time())}"
    itens_atualizados = []
    erros_sap = []

    with db_lock, db() as con:
        material_rows = get_active_material_rows(con)
        classes_ativas = {row["yolo_class"] for row in material_rows}
        classes_para_atualizar = set(deteccoes) & classes_ativas
        if snapshot_completo:
            classes_para_atualizar = classes_ativas

        rows_by_class = {row["yolo_class"]: row for row in material_rows}
        for classe in sorted(classes_para_atualizar):
            row = rows_by_class[classe]
            qtd = int(deteccoes.get(classe, 0))
            qtd_anterior = int(row["qtd"])
            con.execute("update materials set qtd = ? where yolo_class = ?", (qtd, classe))
            mat = {
                "descricao": row["descricao"],
                "sap_matnr": row["sap_matnr"],
                "unidade": row["unidade"],
                "minimo": int(row["minimo"]),
            }
            itens_atualizados.append(
                {
                    "classe": classe,
                    "matnr": mat["sap_matnr"],
                    "descricao": mat["descricao"],
                    "qtd_anterior": qtd_anterior,
                    "qtd_atual": qtd,
                }
            )

            if SAP_MODE == "real":
                try:
                    publicar_no_sap_real(classe, mat, qtd, local)
                except Exception as e:
                    erros_sap.append({"classe": classe, "matnr": mat["sap_matnr"], "erro": str(e)})

        if itens_atualizados:
            con.execute(
                """
                insert into history (documento, local, itens, hora, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (
                    doc_sap,
                    local,
                    len(itens_atualizados),
                    datetime.now().strftime("%H:%M:%S"),
                    datetime.now().isoformat(),
                ),
            )

    ultima_leitura = {
        "fonte": fonte,
        "local": local,
        "deteccoes": {k: int(v) for k, v in deteccoes.items()},
        "timestamp": timestamp or datetime.now().isoformat(),
    }
    notificar_clientes()
    return doc_sap, itens_atualizados, erros_sap


def get_yolo_model():
    global yolo_model
    with model_lock:
        if yolo_model is not None:
            return yolo_model
        import torch
        from ultralytics import YOLO

        original_torch_load = torch.load

        def torch_load_confiavel(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return original_torch_load(*args, **kwargs)

        torch.load = torch_load_confiavel
        yolo_model = YOLO("yolov8n.pt")
        return yolo_model


def image_bytes_from_request():
    if "image" in request.files:
        return request.files["image"].read()

    data = request.get_json(silent=True) or {}
    raw = data.get("image")
    if not raw:
        return None
    if "," in raw:
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def detectar_em_imagem(image_bytes):
    import cv2
    import numpy as np

    img_array = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Imagem invalida")

    model = get_yolo_model()
    results = model(frame, verbose=False)
    boxes = results[0].boxes
    classes = []
    if boxes is not None and len(boxes) > 0:
        for box in boxes:
            classes.append(model.names[int(box.cls[0])])

    with db_lock, db() as con:
        active_classes = {
            row["yolo_class"]
            for row in con.execute("select yolo_class from materials where active = 1").fetchall()
        }
    contagem = dict(Counter(c for c in classes if c in active_classes))
    return contagem


@app.route("/api/materials", methods=["GET", "POST"])
def materials():
    if request.method == "GET":
        with db_lock, db() as con:
            rows = con.execute(
                "select * from materials where active = 1 order by descricao collate nocase"
            ).fetchall()
        return jsonify({"materials": rows_to_materials(rows)})

    data = request.get_json(silent=True) or {}
    yolo_class = (data.get("yolo_class") or "").strip()
    descricao = (data.get("descricao") or "").strip()
    sap_matnr = (data.get("sap_matnr") or "").strip()
    unidade = (data.get("unidade") or "UN").strip().upper()
    minimo = int(data.get("minimo") or 0)
    if not yolo_class or not descricao or not sap_matnr:
        return jsonify({"status": "ERRO", "mensagem": "Classe YOLO, descricao e MATNR sao obrigatorios"}), 400

    with db_lock, db() as con:
        con.execute(
            """
            insert into materials (yolo_class, descricao, sap_matnr, unidade, minimo, qtd, active)
            values (?, ?, ?, ?, ?, 0, 1)
            on conflict(yolo_class) do update set
              descricao=excluded.descricao,
              sap_matnr=excluded.sap_matnr,
              unidade=excluded.unidade,
              minimo=excluded.minimo,
              active=1
            """,
            (yolo_class, descricao, sap_matnr, unidade, minimo),
        )
    notificar_clientes()
    return jsonify({"status": "OK"})


@app.route("/api/materials/<path:yolo_class>", methods=["PUT", "DELETE"])
def material_detail(yolo_class):
    if request.method == "DELETE":
        with db_lock, db() as con:
            con.execute("update materials set active = 0, qtd = 0 where yolo_class = ?", (yolo_class,))
        notificar_clientes()
        return jsonify({"status": "OK"})

    data = request.get_json(silent=True) or {}
    with db_lock, db() as con:
        con.execute(
            """
            update materials
            set descricao = ?, sap_matnr = ?, unidade = ?, minimo = ?
            where yolo_class = ?
            """,
            (
                (data.get("descricao") or "").strip(),
                (data.get("sap_matnr") or "").strip(),
                (data.get("unidade") or "UN").strip().upper(),
                int(data.get("minimo") or 0),
                yolo_class,
            ),
        )
    notificar_clientes()
    return jsonify({"status": "OK"})


@app.route("/api/vision/analyze", methods=["POST"])
def vision_analyze():
    try:
        image_bytes = image_bytes_from_request()
        if not image_bytes:
            return jsonify({"status": "ERRO", "mensagem": "Envie uma imagem"}), 400
        deteccoes = detectar_em_imagem(image_bytes)
        doc_sap, itens, erros = atualizar_snapshot(
            deteccoes,
            request.form.get("local", WAREHOUSE_DEFAULT),
            "camera_navegador",
            snapshot_completo=True,
        )
        return jsonify(
            {
                "status": "OK" if not erros else "PARCIAL",
                "deteccoes": deteccoes,
                "documento_sap": doc_sap,
                "itens": itens,
                "erros_sap": erros,
            }
        ), 207 if erros else 200
    except Exception as e:
        return jsonify({"status": "ERRO", "mensagem": str(e)}), 500


@app.route("/api/sap/mm/stock/update", methods=["POST"])
def atualizar_estoque():
    dados = request.get_json(silent=True) or {}
    deteccoes = dados.get("deteccoes", {})
    local = dados.get("local", WAREHOUSE_DEFAULT)
    fonte = dados.get("fonte", "visao_computacional")
    snapshot_completo = dados.get("snapshot_completo", True)

    doc_sap, itens, erros = atualizar_snapshot(
        deteccoes,
        local,
        fonte,
        timestamp=dados.get("timestamp"),
        snapshot_completo=snapshot_completo,
    )
    estado = build_estado()
    return jsonify(
        {
            "status": "OK" if not erros else "PARCIAL",
            "sy_subrc": 0,
            "documento_sap": doc_sap,
            "mensagem": f"SAP MM: estoque atualizado - {len(itens)} materiais",
            "itens": itens,
            "alertas": len(estado["alertas_reposicao"]),
            "sap_mode": SAP_MODE,
            "erros_sap": erros,
        }
    ), 207 if erros else 200


@app.route("/api/sap/mm/stock", methods=["GET"])
def get_estoque():
    return jsonify(build_estado())


@app.route("/api/sap/mm/stock/reset", methods=["POST"])
def reset():
    global ultima_leitura
    with db_lock, db() as con:
        con.execute("update materials set qtd = 0")
        con.execute("delete from history")
    ultima_leitura = {
        "fonte": "reset manual",
        "local": WAREHOUSE_DEFAULT,
        "deteccoes": {},
        "timestamp": datetime.now().isoformat(),
    }
    notificar_clientes()
    return jsonify({"status": "OK"})


@app.route("/health", methods=["GET"])
def health():
    with db_lock, db() as con:
        total = con.execute("select count(*) as total from materials where active = 1").fetchone()[
            "total"
        ]
    return jsonify({"status": "OK", "sap_mode": SAP_MODE, "materiais": total, "db": str(DB_PATH)})


@app.route("/api/events")
def stream():
    q = queue.Queue()
    with clientes_lock:
        clientes_sse.append(q)

    def gerar():
        yield f"data: {json.dumps(build_estado(), ensure_ascii=False, default=str)}\n\n"
        while True:
            try:
                yield q.get(timeout=30)
            except Exception:
                yield ": heartbeat\n\n"

    return Response(
        gerar(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/")
def index():
    return send_from_directory("dashboard", "index.html")


if __name__ == "__main__":
    init_db()
    testar_conexao()
    print("=" * 55)
    print(f"  SAP Stock Vision - modo: {SAP_MODE.upper()}")
    print("  Dashboard: http://localhost:5001")
    print("  API:       http://localhost:5001/api/sap/mm/stock")
    print("=" * 55)
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        port=int(os.getenv("PORT", "5001")),
        threaded=True,
    )
