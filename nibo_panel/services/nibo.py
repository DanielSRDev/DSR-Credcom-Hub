
import requests
from django.conf import settings

from ..models import StakeholderMap
# (deixe esse import aqui para evitar import circular)
from ..services.categories_map import CATEGORIES  # se quiser usar em algum lugar

BASE_URL = "https://api.nibo.com.br/empresas/v1"


# ---------------------------
# Helpers / infra
# ---------------------------
def _headers():
    token = getattr(settings, "NIBO_API_TOKEN", None)
    if not token:
        raise RuntimeError("Configure NIBO_API_TOKEN no settings.py ou .env")
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "apitoken": token,
    }


def _raise(r: requests.Response):
    try:
        data = r.json()
    except Exception:
        data = r.text
    raise requests.HTTPError(f"{r.status_code} {r.reason} | {data}", response=r)


def only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _get_first_id(url: str) -> str | None:
    r = requests.get(url, headers=_headers(), timeout=30)
    if r.status_code >= 400:
        _raise(r)
    js = r.json() if r.text else {}
    vals = js.get("value") if isinstance(js, dict) else None
    if isinstance(vals, list) and vals:
        return vals[0].get("id")
    return None


# ---------------------------
# Cost center mapping (wrapper p/ manter o import nas views)
# ---------------------------
def map_costcenter_by_id_cob(id_or_sigla) -> str | None:
    from .costcenters_map import COSTCENTER_BY_IDCOB  # local import
    if id_or_sigla is None:
        return None
    return COSTCENTER_BY_IDCOB.get(str(id_or_sigla).strip())


# ---------------------------
# Stakeholders (cliente/fornecedor) com cache em models
# ---------------------------
def _find_or_create(kind: str, nome: str, documento: str) -> str:
    """
    kind: 'customer' ou 'supplier' (atenção: singular!)
    Busca o ID no cache local. Se não houver, procura no Nibo e, se não existir, cria.
    Ao final, persiste no cache (StakeholderMap).
    """
    nome = (nome or "").strip() or "Sem Nome"
    doc_digits = only_digits(documento) or "00000000000"

    # 1) cache local
    cached = StakeholderMap.objects.filter(doc=doc_digits, kind=kind).first()
    if cached:
        return str(cached.nibo_id)

    # 2) procura no Nibo (nome: mais permissivo)
    endpoint = "customers" if kind == "customer" else "suppliers"
    filtro_nome = nome.replace("'", " ")
    url = f"{BASE_URL}/{endpoint}?$filter=contains(name,'{filtro_nome}')&$select=id"
    sid = _get_first_id(url)
    if sid:
        StakeholderMap.objects.update_or_create(
            doc=doc_digits, kind=kind,
            defaults={"nibo_id": sid, "name": nome},
        )
        return sid

    # 3) cria no Nibo
    payload = {
        "name": nome,
        "document": {
            "number": doc_digits,
            "type": "CPF" if len(doc_digits) == 11 else "CNPJ",
        },
    }
    r = requests.post(
        f"{BASE_URL}/{endpoint}/FormatType=json",
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    if r.status_code >= 400:
        _raise(r)
    sid = (r.json() or {}).get("id")
    if not sid:
        _raise(r)

    # 4) grava no cache
    StakeholderMap.objects.update_or_create(
        doc=doc_digits, kind=kind,
        defaults={"nibo_id": sid, "name": nome},
    )
    return sid


def find_or_create_customer(nome: str, documento: str) -> str:
    return _find_or_create("customer", nome, documento)


def find_or_create_supplier(nome: str, documento: str) -> str:
    return _find_or_create("supplier", nome, documento)


# ---------------------------
# Lançamentos (recebimento/pagamento/agendamento)
# ---------------------------
def create_receipt_paid(
    *,
    account_id: str,
    stakeholder_id: str,
    dt: str,
    desc: str,
    reference: str,
    category_id: str,
    value: float,
    costcenter_id: str | None = None,
    accrual_date: str | None = None,
    flag: bool = False,
):
    """
    Conta recebida (receipts). Doc oficial usa fields em minúsculas.
    """
    payload = {
        "accountId": account_id,
        "stakeholderId": stakeholder_id,
        "date": dt,
        "description": desc or "",
        "reference": reference or "",
        "isFlag": bool(flag),
        "accrualDate": accrual_date or dt,
        "categories": [
            {"categoryid": category_id, "value": float(value), "description": ""}
        ],
        "costcenters": (
            [{"costcenterid": costcenter_id, "percent": 100}] if costcenter_id else []
        ),
    }
    r = requests.post(f"{BASE_URL}/receipts", headers=_headers(), json=payload, timeout=40)
    if r.status_code >= 400:
        _raise(r)
    return r.json() if r.text else None


def create_payment_scheduled(
    *,
    stakeholder_id: str,
    dt: str,                 # 'YYYY-MM-DD'
    desc: str,
    reference: str,
    category_id: str,
    value: float,
    costcenter_id: str | None = None,
    accrual_date: str | None = None,
):
    """
    Agendamento (Contas a pagar) — NÃO baixa pagamento.
    Endpoint: POST /schedules/debit/FormatType=json
    """
    url = f"{BASE_URL}/schedules/debit/FormatType=json"
    payload = {
        "stakeholderId": stakeholder_id,
        "description": desc or "",
        "reference": reference or "",
        "scheduleDate": dt,
        "dueDate": dt,
        "accrualDate": accrual_date or dt,
        "categories": [
            {"categoryId": category_id, "value": float(value)}
        ],
        "costCenterValueType": 1,  # %, como já usávamos
        "costCenters": (
            [{"costCenterId": costcenter_id, "percent": 100}] if costcenter_id else []
        ),
    }
    r = requests.post(url, json=payload, headers=_headers(), timeout=40)
    if r.status_code >= 400:
        _raise(r)
    return r.json() if r.text else None
