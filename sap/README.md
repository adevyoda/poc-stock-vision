# SAP BTP ABAP - objetos da POC

Crie estes objetos no Eclipse ADT dentro do sistema ABAP Trial.

Objetivo:

```text
POST /sap/opu/odata4/sap/zpoc_stock_vision/srvd/sap/zpoc_stock_vision/0001/StockVision
```

Payload esperado pelo Python:

```json
{
  "MaterialNumber": "MAT-001",
  "Warehouse": "ALMOX-01",
  "Quantity": 4,
  "Unit": "UN",
  "DetectedAt": "2026-06-25T13:00:00Z",
  "Source": "camera_01"
}
```

Arquivos:

- `zpoc_stock_t.ddls.asddls` - tabela transparente.
- `zpoc_stock_vision.ddls.asddls` - root view entity.
- `zpoc_stock_vision.bdef.asbdef` - behavior para create/update.
- `zpoc_stock_vision_srvd.srvd.srvdsrv` - service definition OData.

Depois de ativar:

1. Criar service binding OData V4 no ADT para `ZPOC_STOCK_VISION_SRVD`.
2. Publicar o binding.
3. Garantir autorizacao/communication arrangement para o client OAuth.
4. No `.env`, alterar `SAP_MODE=real`.
5. Rodar `python sap_config.py` e depois `python server.py`.

Observacao: neste ambiente local, o OAuth retornou token, mas o Catalog Service respondeu HTTP 401. Isso indica que a credencial autentica, mas ainda falta autorizacao/publicacao correta do lado ABAP para consumo OData.
