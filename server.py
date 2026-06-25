"""
POC Stock Vision — Contagem de Estoque por Câmera
Mock SAP MM API + Dashboard em tempo real
Simula integração SAP MM (Materials Management)

SAP_MODE=mock  → sem SAP real (padrão)
SAP_MODE=real  → envia dados ao SAP BTP via OData
"""

import os

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import json, time, threading
from datetime import datetime

try:
    from sap_config import sap_post, SAP_MODE, testar_conexao
except ImportError:
    SAP_MODE = 'mock'
    def sap_post(path, payload): return {'mock': True}
    def testar_conexao(): return True

app = Flask(__name__, static_folder='dashboard', static_url_path='')
CORS(app)

SAP_STOCK_ODATA_PATH = os.getenv(
    'SAP_STOCK_ODATA_PATH',
    '/sap/opu/odata4/sap/zpoc_stock_vision/srvd/sap/zpoc_stock_vision/0001/StockVision'
)
WAREHOUSE_DEFAULT = os.getenv('WAREHOUSE_DEFAULT', 'ALMOX-01')

# ─── Estado em memória (simula tabela MARA/MARD do SAP MM) ───────
estoque = {
    "materiais": {
        "bottle":     {"descricao": "Garrafa",  "sap_matnr": "MAT-001", "qtd": 0, "unidade": "UN", "minimo": 5},
        "cup":        {"descricao": "Copo",     "sap_matnr": "MAT-002", "qtd": 0, "unidade": "UN", "minimo": 10},
        "cell phone": {"descricao": "Celular",  "sap_matnr": "MAT-003", "qtd": 0, "unidade": "UN", "minimo": 2},
        "book":       {"descricao": "Livro",    "sap_matnr": "MAT-004", "qtd": 0, "unidade": "UN", "minimo": 3},
        "scissors":   {"descricao": "Tesoura",  "sap_matnr": "MAT-005", "qtd": 0, "unidade": "UN", "minimo": 2},
        "keyboard":   {"descricao": "Teclado",  "sap_matnr": "MAT-006", "qtd": 0, "unidade": "UN", "minimo": 1},
        "mouse":      {"descricao": "Mouse",    "sap_matnr": "MAT-007", "qtd": 0, "unidade": "UN", "minimo": 1},
        "chair":      {"descricao": "Cadeira",  "sap_matnr": "MAT-008", "qtd": 0, "unidade": "UN", "minimo": 1},
        "person":     {"descricao": "Operador", "sap_matnr": "RH-001",  "qtd": 0, "unidade": "UN", "minimo": 0},
    },
    "historico": [],
    "ultima_leitura": {
        "fonte": "aguardando imagem ou camera",
        "local": WAREHOUSE_DEFAULT,
        "deteccoes": {},
        "timestamp": None,
    },
    "ultima_atualizacao": datetime.now().isoformat(),
    "total_itens": 0,
    "alertas_reposicao": [],
    "sap_mode": SAP_MODE,
}

clientes_sse = []
lock = threading.Lock()

def publicar_no_sap_real(classe, mat, quantidade, local):
    payload = {
        "MaterialNumber": mat["sap_matnr"],
        "Warehouse": local[:10] or WAREHOUSE_DEFAULT,
        "Quantity": int(quantidade),
        "Unit": mat["unidade"],
        "DetectedAt": datetime.utcnow().isoformat(timespec='seconds') + "Z",
        "Source": "camera_01",
    }
    return sap_post(SAP_STOCK_ODATA_PATH, payload)

def notificar_clientes():
    dados = json.dumps(estoque, ensure_ascii=False, default=str)
    msg = f"data: {dados}\n\n"
    with lock:
        mortos = []
        for q in clientes_sse:
            try:
                q.put(msg)
            except Exception:
                mortos.append(q)
        for q in mortos:
            clientes_sse.remove(q)

# ─── MOCK SAP MM API ─────────────────────────────────────────────

@app.route('/api/sap/mm/stock/update', methods=['POST'])
def atualizar_estoque():
    dados = request.get_json(silent=True) or {}
    deteccoes = dados.get('deteccoes', {})
    local = dados.get('local', WAREHOUSE_DEFAULT)
    fonte = dados.get('fonte', 'visao_computacional')

    doc_sap = f"INV{int(time.time())}"
    itens_atualizados = []
    alertas_novos = []
    erros_sap = []

    for classe, qtd in deteccoes.items():
        if classe in estoque['materiais']:
            mat = estoque['materiais'][classe]
            qtd_anterior = mat['qtd']
            mat['qtd'] = int(qtd)

            if mat['qtd'] < mat['minimo'] and mat['minimo'] > 0:
                alertas_novos.append({
                    "tipo": "REPOSICAO_NECESSARIA",
                    "matnr": mat['sap_matnr'],
                    "descricao": mat['descricao'],
                    "qtd_atual": mat['qtd'],
                    "qtd_minima": mat['minimo'],
                    "hora": datetime.now().strftime('%H:%M:%S')
                })

            itens_atualizados.append({
                "matnr": mat['sap_matnr'],
                "descricao": mat['descricao'],
                "qtd_anterior": qtd_anterior,
                "qtd_atual": mat['qtd'],
            })

            if SAP_MODE == 'real':
                try:
                    publicar_no_sap_real(classe, mat, mat['qtd'], local)
                except Exception as e:
                    erros_sap.append({
                        "classe": classe,
                        "matnr": mat['sap_matnr'],
                        "erro": str(e),
                    })

    estoque['alertas_reposicao'] = (alertas_novos + estoque['alertas_reposicao'])[:5]
    estoque['ultima_leitura'] = {
        "fonte": fonte,
        "local": local,
        "deteccoes": deteccoes,
        "timestamp": dados.get('timestamp') or datetime.now().isoformat(),
    }

    if itens_atualizados:
        estoque['historico'] = [{
            "documento": doc_sap,
            "local": local,
            "itens": len(itens_atualizados),
            "hora": datetime.now().strftime('%H:%M:%S'),
        }] + estoque['historico'][:9]

    estoque['total_itens'] = sum(m['qtd'] for k, m in estoque['materiais'].items() if k != 'person')
    estoque['ultima_atualizacao'] = datetime.now().isoformat()

    notificar_clientes()

    http_status = 207 if erros_sap else 200
    return jsonify({
        "status": "OK" if not erros_sap else "PARCIAL",
        "sy_subrc": 0,
        "documento_sap": doc_sap,
        "mensagem": f"SAP MM: estoque atualizado — {len(itens_atualizados)} materiais",
        "itens": itens_atualizados,
        "alertas": len(alertas_novos),
        "sap_mode": SAP_MODE,
        "erros_sap": erros_sap,
    }), http_status

@app.route('/api/sap/mm/stock', methods=['GET'])
def get_estoque():
    return jsonify(estoque)

@app.route('/api/sap/mm/stock/reset', methods=['POST'])
def reset():
    for m in estoque['materiais'].values():
        m['qtd'] = 0
    estoque['historico'] = []
    estoque['alertas_reposicao'] = []
    estoque['total_itens'] = 0
    estoque['ultima_atualizacao'] = datetime.now().isoformat()
    notificar_clientes()
    return jsonify({"status": "OK"})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "OK",
        "sap_mode": SAP_MODE,
        "materiais": len(estoque['materiais']),
    })

# ─── SSE ─────────────────────────────────────────────────────────

@app.route('/api/events')
def stream():
    import queue
    q = queue.Queue()
    with lock:
        clientes_sse.append(q)

    def gerar():
        yield f"data: {json.dumps(estoque, ensure_ascii=False, default=str)}\n\n"
        while True:
            try:
                yield q.get(timeout=30)
            except Exception:
                yield ": heartbeat\n\n"

    return Response(gerar(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

# ─── Dashboard ───────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('dashboard', 'index.html')

# ─── Main ────────────────────────────────────────────────────────

if __name__ == '__main__':
    testar_conexao()
    print("=" * 55)
    print(f"  SAP Stock Vision — modo: {SAP_MODE.upper()}")
    print("  Dashboard: http://localhost:5001")
    print("  API:       http://localhost:5001/api/sap/mm/stock")
    print("=" * 55)
    app.run(
        host=os.getenv('HOST', '0.0.0.0'),
        debug=os.getenv('FLASK_DEBUG', '0') == '1',
        port=int(os.getenv('PORT', '5001')),
        threaded=True
    )
