"""
SAP BTP ABAP Cloud — Auth & API Helper
Sistema TRL · Trial US10 · Fernando Leopoldino

Uso em qualquer POC:
    from sap_config import sap_get, sap_post, get_token, SAP_MODE
"""

import os, sys, time, json
import requests
from pathlib import Path

# Carrega .env da pasta pocs/ (funciona de qualquer subpasta)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    load_dotenv(dotenv_path=env_path)
except ImportError:
    pass  # sem dotenv — usa variáveis de ambiente do sistema

# ─── Configuração ──────────────────────────────────────────────────
SAP_URL          = os.getenv('SAP_URL', '')
SAP_WEB_URL      = os.getenv('SAP_WEB_URL', '')
SAP_UAA_URL      = os.getenv('SAP_UAA_URL', '')
SAP_CLIENT_ID    = os.getenv('SAP_CLIENT_ID', '')
SAP_CLIENT_SECRET= os.getenv('SAP_CLIENT_SECRET', '')
SAP_CLIENT       = os.getenv('SAP_CLIENT', '100')
SAP_CATALOG_PATH = os.getenv('SAP_CATALOG_PATH', '/sap/opu/odata/IWFND/CATALOGSERVICE;v=2')
SAP_MODE         = os.getenv('SAP_MODE', 'mock')  # 'mock' | 'real'

# ─── Cache de token ────────────────────────────────────────────────
_token_cache = {'token': None, 'expires_at': 0}

def get_token() -> str:
    """
    Obtém Bearer token via OAuth2 client_credentials.
    Faz cache por ~12h (renova 60s antes de expirar).
    """
    if SAP_MODE == 'mock':
        return 'mock-token'

    now = time.time()
    if _token_cache['token'] and now < _token_cache['expires_at'] - 60:
        return _token_cache['token']

    print(f"[SAP Auth] Obtendo token: {SAP_UAA_URL}/oauth/token")
    r = requests.post(
        f"{SAP_UAA_URL}/oauth/token",
        auth=(SAP_CLIENT_ID, SAP_CLIENT_SECRET),
        data={'grant_type': 'client_credentials'},
        timeout=15
    )
    if not r.ok:
        raise RuntimeError(f"[SAP Auth] Falha: {r.status_code} — {r.text[:200]}")

    data = r.json()
    _token_cache['token'] = data['access_token']
    _token_cache['expires_at'] = now + data.get('expires_in', 43200)
    print(f"[SAP Auth] Token OK - expira em {data.get('expires_in', 43200)//3600}h")
    return _token_cache['token']

def _headers() -> dict:
    return {
        'Authorization': f'Bearer {get_token()}',
        'Accept': 'application/json',
        'sap-client': SAP_CLIENT,
    }

# ─── HTTP helpers ──────────────────────────────────────────────────

def sap_get(path: str, params: dict = None) -> dict:
    """GET para qualquer endpoint OData do SAP BTP."""
    if SAP_MODE == 'mock':
        return {'mock': True, 'path': path}
    url = f"{SAP_URL}{path}"
    r = requests.get(url, headers=_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def sap_post(path: str, payload: dict) -> dict:
    """POST para endpoints OData do SAP BTP (cria/atualiza entidades)."""
    if SAP_MODE == 'mock':
        return {'mock': True, 'path': path, 'payload': payload}
    url = f"{SAP_URL}{path}"
    headers = _headers()
    headers['Content-Type'] = 'application/json'
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()

def listar_servicos_odata() -> list:
    """
    Lista os serviços OData disponíveis no sistema via Catalog Service.
    Equivale a abrir /IWFND/MAINT_SERVICE no SAP GUI.
    """
    try:
        dados = sap_get(SAP_CATALOG_PATH, params={'$format': 'json', '$top': '50'})
        servicos = dados.get('d', {}).get('EntitySets', [])
        return servicos
    except Exception as e:
        print(f"[SAP Catalog] Erro: {e}")
        return []

# ─── Teste de conexão ──────────────────────────────────────────────

def testar_conexao() -> bool:
    """
    Testa autenticação e conectividade com o SAP BTP.
    Retorna True se OK.
    """
    print("\n" + "="*55)
    print(f"  SAP BTP Connection Test - Sistema {os.getenv('SAP_SYSTEM_ID','TRL')}")
    print("="*55)
    print(f"  URL:    {SAP_URL}")
    print(f"  UAA:    {SAP_UAA_URL}")
    print(f"  Modo:   {SAP_MODE.upper()}")
    print("-"*55)

    if SAP_MODE == 'mock':
        print("  [OK] Modo MOCK - sem conexao real com SAP")
        print("  Para conectar: SAP_MODE=real no .env")
        return True

    try:
        token = get_token()
        print(f"  [OK] Token obtido: {token[:30]}...")

        # Testa catálogo
        r = requests.get(
            f"{SAP_URL}{SAP_CATALOG_PATH}",
            headers=_headers(),
            params={'$format': 'json', '$top': '5'},
            timeout=15
        )
        print(f"  [OK] Catalogo OData: HTTP {r.status_code}")
        if r.ok:
            print(f"  [OK] Conexao com SAP BTP confirmada!")
            return True
        else:
            print(f"  [WARN] Catalogo respondeu: {r.status_code}")
            return False

    except Exception as e:
        print(f"  [ERRO] {e}")
        return False
    finally:
        print("="*55 + "\n")


if __name__ == '__main__':
    # python sap_config.py  →  testa conexão
    ok = testar_conexao()
    sys.exit(0 if ok else 1)
