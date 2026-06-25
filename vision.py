"""
POC Stock Vision — Contagem de Estoque por Câmera
Detecta objetos com YOLOv8 e atualiza SAP MM em tempo real

Uso:
  python vision.py                    # usa webcam
  python vision.py --video demo.mp4   # usa vídeo
  python vision.py --image foto.jpg   # usa uma imagem real
  python vision.py --demo             # modo demo sem câmera
"""

import cv2
import os
import requests
import time
import argparse
import random
import threading
from datetime import datetime
from collections import Counter

SAP_API = os.getenv("SAP_API", "http://localhost:5001/api/sap/mm/stock/update")

# Classes YOLO que mapeamos para materiais SAP
CLASSES_INTERESSE = {
    'bottle', 'cup', 'cell phone', 'book',
    'scissors', 'keyboard', 'mouse', 'chair', 'person'
}

def enviar_para_sap(deteccoes, local="Almoxarifado-01", fonte="camera_yolov8"):
    """Envia contagem para Mock SAP MM API"""
    payload = {
        "deteccoes": deteccoes,
        "local": local,
        "fonte": fonte,
        "timestamp": datetime.now().isoformat()
    }
    try:
        r = requests.post(SAP_API, json=payload, timeout=2)
        resp = r.json()
        print(f"[SAP MM OK] {resp['mensagem']} | Doc: {resp.get('documento_sap','-')}")
        if resp.get('alertas', 0) > 0:
            print(f"[SAP MM WARN] {resp['alertas']} alerta(s) de reposicao gerado(s)!")
    except Exception as e:
        print(f"[SAP MM ERRO] {e}")

def modo_demo():
    """Modo demo sem câmera — simula detecção de estoque"""
    print("\n[DEMO] Iniciando simulação SAP MM Stock Vision...")
    print("[DEMO] Pressione Ctrl+C para parar\n")

    ciclo = 0
    try:
        while True:
            ciclo += 1
            print(f"\n--- Contagem #{ciclo} | {datetime.now().strftime('%H:%M:%S')} ---")

            # Simula variações de estoque (às vezes cai abaixo do mínimo)
            deteccoes = {
                "bottle":     random.randint(0 if ciclo % 7 == 0 else 3, 12),
                "cup":        random.randint(0 if ciclo % 5 == 0 else 8, 20),
                "book":       random.randint(0 if ciclo % 9 == 0 else 2, 6),
                "cell phone": random.randint(0, 3),
                "scissors":   random.randint(0 if ciclo % 4 == 0 else 1, 4),
            }

            print("[YOLO] Detectado:", deteccoes)
            enviar_para_sap(deteccoes)
            time.sleep(4)

    except KeyboardInterrupt:
        print("\n[DEMO] Simulação encerrada.")

def carregar_modelo():
    try:
        import torch
        from ultralytics import YOLO
    except ImportError:
        print("[ERRO] ultralytics nao instalado.")
        print("       Execute: pip install ultralytics")
        return None

    # Compatibilidade com PyTorch >= 2.6 para pesos oficiais do YOLO.
    original_torch_load = torch.load
    def torch_load_confiavel(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original_torch_load(*args, **kwargs)
    torch.load = torch_load_confiavel

    print("\n[YOLO] Carregando YOLOv8n...")
    model = YOLO('yolov8n.pt')
    print("[YOLO] Pronto!\n")
    return model

def contar_classes(model, frame):
    results = model(frame, verbose=False)
    boxes = results[0].boxes

    classes_detectadas = []
    if boxes is not None and len(boxes) > 0:
        for box in boxes:
            nome = model.names[int(box.cls[0])]
            classes_detectadas.append(nome)

    contagem = dict(Counter(classes_detectadas))
    contagem_filtrada = {k: v for k, v in contagem.items() if k in CLASSES_INTERESSE}
    return results, contagem_filtrada

def modo_imagem(path):
    """Modo simples: le uma imagem real, conta objetos e atualiza o SAP."""
    model = carregar_modelo()
    if model is None:
        return

    frame = cv2.imread(path)
    if frame is None:
        print(f"[ERRO] Nao consegui abrir a imagem: {path}")
        return

    results, contagem_filtrada = contar_classes(model, frame)
    print("[YOLO] Imagem analisada:", path)
    print("[YOLO] Detectado:", contagem_filtrada or "nenhum material mapeado")

    if contagem_filtrada:
        enviar_para_sap(contagem_filtrada, local="Almoxarifado-01", fonte=f"imagem:{path}")

    annotated = results[0].plot()
    output = "deteccao_resultado.jpg"
    cv2.imwrite(output, annotated)
    print(f"[YOLO] Resultado visual salvo em: {output}")

def modo_webcam(source=0):
    """Modo real com YOLOv8 + câmera"""
    model = carregar_modelo()
    if model is None:
        return

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[ERRO] Câmera/vídeo não disponível: {source}")
        return

    ultimo_envio = 0
    INTERVALO = 3
    ultimo_detalhes = {}

    print(f"[CAM] Detectando objetos... Enviando para SAP MM a cada {INTERVALO}s")
    print("[CAM] Aponte a câmera para objetos em uma mesa")
    print("[CAM] Pressione 'q' para sair\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        results, contagem_filtrada = contar_classes(model, frame)

        # Desenha resultado
        annotated = results[0].plot()
        y = 30
        cv2.rectangle(annotated, (0, 0), (280, 20 + len(contagem_filtrada) * 22 + 20), (0,0,0), -1)
        cv2.putText(annotated, "SAP MM — Estoque Detectado:", (8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 212, 255), 1)
        y += 22
        for nome, qtd in contagem_filtrada.items():
            cv2.putText(annotated, f"  {nome}: {qtd}", (8, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 255, 200), 1)
            y += 20

        cv2.imshow('SAP Stock Vision (q=sair)', annotated)

        # Envia para SAP a cada INTERVALO segundos
        agora = time.time()
        if agora - ultimo_envio >= INTERVALO and contagem_filtrada:
            threading.Thread(
                target=enviar_para_sap,
                args=(contagem_filtrada,),
                daemon=True
            ).start()
            ultimo_envio = agora

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SAP Stock Vision — Contagem de Estoque')
    parser.add_argument('--video', type=str, help='Arquivo de vídeo')
    parser.add_argument('--image', type=str, help='Arquivo de imagem')
    parser.add_argument('--demo', action='store_true', help='Modo demo sem câmera')
    parser.add_argument('--cam', type=int, default=0, help='Câmera (padrão: 0)')
    args = parser.parse_args()

    if args.demo:
        modo_demo()
    elif args.image:
        modo_imagem(args.image)
    elif args.video:
        modo_webcam(args.video)
    else:
        modo_webcam(args.cam)
