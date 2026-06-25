# SAP Stock Vision

POC simples para explicar uma ideia forte:

> A camera olha para uma mesa de estoque, a IA conta os produtos e o SAP MM recebe a atualizacao.

## Historia da demo

1. Cadastre somente os materiais que fazem sentido para estoque.
2. Abra a camera pelo dashboard ou envie uma foto.
3. O Flask recebe a imagem e roda YOLO localmente.
4. A contagem atualiza a base SQLite local e o dashboard em tempo real.
5. O mesmo fluxo gera um documento mock SAP MM.
6. Com `SAP_MODE=real`, o payload e enviado para o OData do SAP BTP ABAP.

## Rodar em 2 minutos

```powershell
cd C:\_personal\SAP\pocs\poccase1\repo-sappoccase1
pip install -r requirements.txt
Copy-Item .env.example .env
python server.py
```

Abra:

```text
http://localhost:5001
```

Na tela, use `Cadastrar material de estoque`, `Ligar camera` e `Capturar e detectar`.
Tambem existe o modo terminal:

```powershell
# Demo automatica, sem camera
python vision.py --demo

# Imagem real
python vision.py --image C:\caminho\foto.jpg

# Imagem real apontando explicitamente para API local
python vision.py --image C:\caminho\foto.jpg --api http://127.0.0.1:5001/api/sap/mm/stock/update

# Webcam real
python vision.py

# Video real
python vision.py --video C:\caminho\video.mp4
```

Para enviar a contagem para a URL publica atual no Worker da Fleop:

```powershell
python vision.py --image C:\caminho\foto.jpg --api https://sap.fleop.com.br/poccase1/api/sap/mm/stock/update
```

## O que e real e o que e mock

Real:

- base SQLite local em `stock_vision.db`;
- cadastro/remocao de materiais de estoque;
- camera no navegador via `getUserMedia`;
- leitura de imagem, video ou webcam;
- deteccao com YOLOv8;
- contagem enviada por HTTP;
- dashboard em tempo real via SSE;
- payload pronto para SAP OData;
- endpoint publico em `https://sap.fleop.com.br/poccase1` via Cloudflare Worker.

Mock enquanto `SAP_MODE=mock`:

- a atualizacao SAP fica em memoria no Flask, simulando MM.
- o Worker publico responde em modo `worker-mock` ate a VPS/Flask real ser conectada.

Real quando `SAP_MODE=real`:

- `server.py` chama `sap_post()` em `sap_config.py`;
- o endpoint usado vem de `SAP_STOCK_ODATA_PATH`;
- o SAP precisa ter o servico RAP/OData publicado.

## Variaveis

```env
SAP_MODE=mock
SAP_URL=https://SEU-SISTEMA.abap.us10.hana.ondemand.com
SAP_UAA_URL=https://SEU-TENANT.authentication.us10.hana.ondemand.com
SAP_CLIENT_ID=sb-...
SAP_CLIENT_SECRET=...
SAP_STOCK_ODATA_PATH=/sap/opu/odata4/sap/zpoc_stock_vision/srvd/sap/zpoc_stock_vision/0001/StockVision
PORT=5001
HOST=0.0.0.0
WAREHOUSE_DEFAULT=ALMOX-01
```

## Deploy VPS

O servidor da VPS precisa rodar apenas o Flask. A visao computacional roda localmente perto da camera e envia para a URL publica.

```powershell
docker compose up -d --build
```

No Caddy, use o conteudo de `Caddyfile.poccase1` para publicar:

```text
https://sap.fleop.com.br/poccase1
```

Depois, a camera local envia para:

```powershell
$env:SAP_API="https://sap.fleop.com.br/poccase1/api/sap/mm/stock/update"
python vision.py --image C:\caminho\foto.jpg
```

## Endpoint principal

```http
POST /api/sap/mm/stock/update
Content-Type: application/json
```

```json
{
  "local": "ALMOX-01",
  "fonte": "imagem:C:\\mesa.jpg",
  "deteccoes": {
    "bottle": 4,
    "cup": 8,
    "book": 2
  }
}
```

## Endpoints locais da POC

```text
GET    /                         dashboard
GET    /health                   status da API
GET    /api/sap/mm/stock         estoque atual
POST   /api/sap/mm/stock/update  atualiza contagem
POST   /api/sap/mm/stock/reset   zera estoque e historico
GET    /api/materials            lista materiais cadastrados
POST   /api/materials            cria/atualiza material
DELETE /api/materials/<classe>   remove material do estoque
POST   /api/vision/analyze       recebe foto/frame e roda YOLO local
GET    /api/events               eventos em tempo real para dashboard
```
