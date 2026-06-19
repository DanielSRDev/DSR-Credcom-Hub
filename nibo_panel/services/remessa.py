"""
Servico unico de envio de remessa para o Nibo.

Centraliza a logica que antes vivia dentro da view enviar_remessa, para que
TANTO o envio manual (painel) QUANTO o envio automatico (comando agendado)
usem exatamente as mesmas regras (categorias, VB, AM3, vencimento +15,
centro de custo). Assim nao ha risco de divergencia entre os dois caminhos.

Cada processar_* trata UMA linha de uma tabela e reporta o resultado num
RelatorioRemessa (avisos/erros/processados), sem depender de request/messages.
"""

import unicodedata
from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import connection

from .categories_map import CATEGORIES as CAT
from .nibo import (
    find_or_create_customer,
    find_or_create_supplier,
    create_receipt_paid,
    create_payment_scheduled,
    map_costcenter_by_id_cob,
    only_digits,
)

# ============================================================
# CONFIG CODIGO VB
# ============================================================
VB_CREDOR_ID = 194298103


def _norm_key(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")
    return s.strip().upper()


VB_MAP = {
    _norm_key("Residencial Alvino Albino"): "VB10",
    _norm_key("Residencial Arco do Triunfo"): "VB7",
    _norm_key("Residencial Arco Iris"): "VB15",
    _norm_key("Residencial Arco Iris 2"): "VB26",
    _norm_key("Residencial Bela Vista"): "VB24",
    _norm_key("Residencial Boa Vista"): "VB30",
    _norm_key("Residencial Boa Vista II"): "VB35",
    _norm_key("Residencial Brisas da Serra"): "VB6",
    _norm_key("Residencial Cecilia"): "VB12",
    _norm_key("Residencial Cecilia SMA"): "VB22",
    _norm_key("Residencial Dona Genesi"): "VB40",
    _norm_key("Residencial Dori"): "VB19",
    _norm_key("Residencial Drº Zelia"): "VB29",
    _norm_key("Residencial Goiania Sul"): "VB4",
    _norm_key("Residencial Ipanema"): "VB11",
    _norm_key("Residencial Isabella"): "VB41",
    _norm_key("Residencial Jair Ferreira"): "VB21",
    _norm_key("Residencial Jardim dos Ipes"): "VB18",
    _norm_key("Residencial Jardim Goias"): "VB33",
    _norm_key("Residencial Jardim Goias II"): "VB25",
    _norm_key("Residencial Jardim Pacifico"): "VB16",
    _norm_key("Residencial Juarez Freire"): "VB37",
    _norm_key("Residencial Lago Azul II"): "VB2",
    _norm_key("Residencial Madre Germana"): "VB39",
    _norm_key("Residencial Maria Amelia"): "VB3",
    _norm_key("Residencial Maria Amelia 2"): "VB5",
    _norm_key("Residencial Maria Oliveira"): "VB20",
    _norm_key("Residencial Monte Cristo"): "VB36",
    _norm_key("Residencial Morada do Bosque"): "VB31",
    _norm_key("Residencial Nelson Mariotto"): "VB14",
    _norm_key("Residencial Novo Horizonte"): "VB38",
    _norm_key("Residencial Paineiras"): "VB9",
    _norm_key("Residencial Paraiso"): "VB17",
    _norm_key("Residencial Parque dos Girassois"): "VB34",
    _norm_key("Residencial Santa Fe"): "VB1",
    _norm_key("Residencial Sao Jose"): "VB8",
    _norm_key("Residencial São Paulo"): "VB23",
    _norm_key("Residencial Sao Paulo II"): "VB27",
    _norm_key("Residencial Triunfo II"): "VB32",
    _norm_key("Residencial Villar Santana"): "VB28",
    _norm_key("Residencial Eldorado"): "VB13",
    _norm_key("Residencial Madre Germana II - Extensão"): "VB39",
    _norm_key("Residencial Sao Paulo"): "VB23",
    _norm_key("Goianira"): "VB7",
}


def vb_reference(credor_id, filial_nome, default_reference):
    try:
        if int(credor_id) == VB_CREDOR_ID:
            code = VB_MAP.get(_norm_key((filial_nome or "").strip()))
            if code:
                return code
    except Exception:
        pass
    return default_reference


def vb_code_only(credor_id, filial_nome):
    return vb_reference(credor_id, filial_nome, "") or ""


# ============================================================
# CONFIG TABELAS E PKs
# ============================================================
TB = {
    "repasse": "tb_repasse",
    "repassevr": "tb_repassevr",
    "despesa": "tb_despesa",
    "contareceber": "tb_contareceber",
    "contapagar": "tb_contaspagar",
}
PK_COL = {
    "tb_repasse": "rep_id_local",
    "tb_repassevr": "repvr_id_local",
    "tb_despesa": "des_id_local",
    "tb_contareceber": "cr_id_local",
    "tb_contaspagar": "cp_id_local",
}

# ============================================================
# REGRAS AM3
# ============================================================
AM3_CREDOR_ID = 194298055
FILIAIS_50 = {
    "JD BOUGAINVILLE",
    "JARDIM PARIS 64",
    "PARQUE AMAZONAS 65",
    "JARDIM MILAO 61",
    "JD MADRI",
    "JARDIM BOUGAINVILLE",
}

# ============================================================
# HELPERS SQL
# ============================================================
def qexec(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.rowcount


def qfetchall(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def qfetchone(sql, params=None):
    rows = qfetchall(sql, params)
    return rows[0] if rows else None


def vcto_mais_15(pgo_data):
    dt = pgo_data if isinstance(pgo_data, datetime) else datetime.combine(pgo_data, datetime.min.time())
    return (dt.date() + timedelta(days=15)).strftime("%Y-%m-%d")


# ============================================================
# HELPERS DE REGRA / DESCRICAO / NORMALIZACAO
# ============================================================
def _desc(filial, obs):
    filial = (filial or "").strip()
    obs = (obs or "").strip()
    if filial and obs:
        return f"{filial} + {obs}"
    return filial or obs or ""


def _norm_filial(name):
    return (name or "").strip().upper()


def _categoria_cr_in_contareceber(row):
    credor_id = row.get("credor_id")
    atraso = row.get("rec_atraso") or 0
    filial_u = _norm_filial(row.get("filial_nome"))
    dup = bool(row.get("dup"))
    if credor_id == AM3_CREDOR_ID:
        if dup:
            if atraso > 120:
                return CAT["HON_50_50_IN"] if filial_u in FILIAIS_50 else CAT["HON_60_40_IN"]
            return CAT["HONORARIOS_IN"]
        return CAT["HONORARIOS_IN"]
    return CAT["HONORARIOS_IN"]


def _categoria_cp_out_contapagar(row):
    credor_id = row.get("credor_id")
    atraso = row.get("rec_atraso") or 0
    filial_u = _norm_filial(row.get("filial_nome"))
    if credor_id == AM3_CREDOR_ID and atraso > 120:
        return CAT["HON_50_50_OUT"] if filial_u in FILIAIS_50 else CAT["HON_60_40_OUT"]
    return CAT["REPASSES_OUT"]


def _min_receipt_date():
    s = getattr(settings, "NIBO_ACCOUNT_MIN_DATE", None)
    if s:
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            pass
    return None


def _last_con_obs_by_pgo(pgo_id):
    if not pgo_id:
        return None
    r = qfetchone(
        "SELECT con_obs FROM tb_repasse WHERE pgo_id = %s ORDER BY COALESCE(pgo_data, NOW()) DESC LIMIT 1",
        [pgo_id],
    )
    if r and r.get("con_obs"):
        return r["con_obs"]
    rv = qfetchone(
        "SELECT con_obs FROM tb_repassevr WHERE pgo_id = %s ORDER BY COALESCE(pgo_data, NOW()) DESC LIMIT 1",
        [pgo_id],
    )
    return rv["con_obs"] if rv and rv.get("con_obs") else None


def _to_dec(val):
    """Converte para Decimal com 2 casas. Retorna None se < 0,01."""
    try:
        d = Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        d = Decimal("0.00")
    return d if d >= Decimal("0.01") else None


def get_by_id(table, _id):
    pk = PK_COL[table]
    row = qfetchone(f"SELECT * FROM {table} WHERE {pk} = %s", [_id])
    if row:
        row["id"] = row[pk]
    return row


def load_repasse_base_by_aco(aco_id):
    vr = qfetchone(
        """
        SELECT pgo_data, cliente_nome, cliente_cpfcnpj, credor_sigla,
               filial_nome, con_obs, credor_id, vlr_repasse, ope_nome
          FROM tb_repassevr
         WHERE aco_id = %s
         ORDER BY COALESCE(pgo_data, NOW()) DESC LIMIT 1
        """,
        [aco_id],
    )
    if vr:
        return vr
    return qfetchone(
        """
        SELECT pgo_data, cliente_nome, cliente_cpfcnpj, credor_sigla,
               filial_nome, con_obs, credor_id, vlr_repasse, ope_nome
          FROM tb_repasse
         WHERE aco_id = %s
         ORDER BY COALESCE(pgo_data, NOW()) DESC LIMIT 1
        """,
        [aco_id],
    )


def send_receipt(account_id, *, stakeholder_id, dt, desc, reference, category_id, value, costcenter_id):
    return create_receipt_paid(
        account_id=account_id,
        stakeholder_id=stakeholder_id,
        dt=dt, desc=desc, reference=reference,
        category_id=category_id, value=float(value),
        costcenter_id=costcenter_id, accrual_date=dt, flag=False,
    )


def send_payment(*, stakeholder_id, vcto, desc, reference, category_id, value, costcenter_id):
    return create_payment_scheduled(
        stakeholder_id=stakeholder_id,
        dt=vcto, desc=desc, reference=reference,
        category_id=category_id, value=float(value),
        costcenter_id=costcenter_id, accrual_date=vcto,
    )


# ============================================================
# RELATORIO (coletor de resultado, sem depender de request)
# ============================================================
class RelatorioRemessa:
    def __init__(self):
        self.processados = 0
        self.avisos = []
        self.erros = []

    def aviso(self, msg):
        self.avisos.append(str(msg))

    def erro(self, msg):
        self.erros.append(str(msg))

    @property
    def total_avisos(self):
        return len(self.avisos)

    @property
    def total_erros(self):
        return len(self.erros)


def _marcar_enviado(table, _id):
    qexec(f"UPDATE {table} SET enviado = TRUE WHERE {PK_COL[table]} = %s", [_id])


# ============================================================
# PROCESSADORES POR TABELA (uma linha cada)
#
# exigir_cc=True  -> pula registros sem centro de custo mapeado (uso automatico)
# dry_run=True    -> nao chama a API nem marca enviado (so simula/valida)
# ============================================================
def processar_repasse(_id, account_id, cc_padrao, rep, *, exigir_cc=False, dry_run=False):
    row = get_by_id(TB["repasse"], _id)
    if not row:
        return

    valor_rep = _to_dec(row.get("vlr_repasse"))
    if valor_rep is None:
        rep.aviso(f"tb_repasse id={row['id']} ignorado: valor zerado ou invalido.")
        return

    try:
        pgo_dt = row.get("pgo_data") or datetime.now()
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        cc_id = map_costcenter_by_id_cob(row.get("credor_id") or row.get("credor_sigla")) or cc_padrao
        if exigir_cc and not cc_id:
            rep.aviso(f"tb_repasse id={row['id']} (acordo {row.get('aco_id')}) pulado: credor sem centro de custo mapeado.")
            return

        min_dt = _min_receipt_date()
        send_dt = pgo_dt.date()
        if min_dt and send_dt < min_dt:
            send_dt = min_dt
            rep.aviso(
                f"tb_repasse id={row['id']} (acordo {row.get('aco_id')}) com data {pgo_dt.date()} "
                f"ajustada para {send_dt} (>= saldo inicial da conta)."
            )
        dt_str = send_dt.strftime("%Y-%m-%d")

        desc = _desc(row.get("filial_nome"), row.get("con_obs"))
        vb_code = vb_code_only(row.get("credor_id"), row.get("filial_nome"))
        if vb_code:
            desc = f"{desc} {vb_code}"
        aco_id = row.get("aco_id")
        reference = str(row.get("ope_nome") or "").strip() or str(aco_id or "")

        if dry_run:
            rep.processados += 1
            return

        cliente_nome = row.get("cliente_nome") or "Sem Nome"
        cliente_doc = only_digits(row.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_cliente = find_or_create_customer(cliente_nome, cliente_doc)
        stakeholder_fornecedor = find_or_create_supplier(cliente_nome, cliente_doc)

        send_receipt(
            account_id,
            stakeholder_id=stakeholder_cliente,
            dt=dt_str, desc=desc, reference=reference,
            category_id=CAT["REPASSES_IN"], value=valor_rep, costcenter_id=cc_id,
        )
        vcto = vcto_mais_15(pgo_dt)
        send_payment(
            stakeholder_id=stakeholder_fornecedor,
            vcto=vcto, desc=desc, reference=reference,
            category_id=CAT["REPASSES_OUT"], value=valor_rep, costcenter_id=cc_id,
        )
        _marcar_enviado(TB["repasse"], row["id"])
        rep.processados += 1
    except Exception as e:
        rep.erro(f"tb_repasse id={row['id']} falhou: {e}")


def processar_repassevr(_id, account_id, cc_padrao, rep, *, exigir_cc=False, dry_run=False):
    row = get_by_id(TB["repassevr"], _id)
    if not row:
        return

    valor_dec = _to_dec(row.get("vlr_repasse"))
    if valor_dec is None:
        rep.aviso(f"tb_repassevr id={row.get('id')} ignorado: valor < 0,01.")
        return

    try:
        pgo_dt = row.get("pgo_data") or datetime.now()
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        cc_id = map_costcenter_by_id_cob(row.get("credor_id") or row.get("credor_sigla")) or cc_padrao
        if exigir_cc and not cc_id:
            rep.aviso(f"tb_repassevr id={row['id']} (acordo {row.get('aco_id')}) pulado: credor sem centro de custo mapeado.")
            return

        dt_str = pgo_dt.strftime("%Y-%m-%d")
        vcto = (pgo_dt.date() + timedelta(days=15)).strftime("%Y-%m-%d")

        aco_id = row.get("aco_id")
        desc = _desc(row.get("filial_nome"), row.get("con_obs"))
        vb_code = vb_code_only(row.get("credor_id"), row.get("filial_nome"))
        is_vb = bool(vb_code)
        if is_vb:
            desc = f"{desc} {vb_code}"
        reference = str(row.get("ope_nome") or "").strip() or str(aco_id or "")
        cliente_nome = row.get("cliente_nome") or "Sem Nome"

        if dry_run:
            rep.processados += 1
            return

        cliente_doc = only_digits(row.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_cliente = find_or_create_customer(cliente_nome, cliente_doc)
        stakeholder_fornecedor = find_or_create_supplier(cliente_nome, cliente_doc)

        send_receipt(
            account_id,
            stakeholder_id=stakeholder_cliente,
            dt=dt_str, desc=desc, reference=reference,
            category_id=CAT["REPASSES_IN"], value=valor_dec, costcenter_id=cc_id,
        )
        desc_pay = desc if is_vb else f"Repasse {aco_id} - {cliente_nome}"
        send_payment(
            stakeholder_id=stakeholder_fornecedor,
            vcto=vcto, desc=desc_pay, reference=reference,
            category_id=CAT["REPASSES_OUT"], value=valor_dec, costcenter_id=cc_id,
        )
        _marcar_enviado(TB["repassevr"], row["id"])
        rep.processados += 1
    except Exception as e:
        rep.erro(f"tb_repassevr id={row['id']} falhou: {e}")


def processar_contapagar(_id, account_id, cc_padrao, rep, *, exigir_cc=False, dry_run=False):
    row = get_by_id(TB["contapagar"], _id)
    if not row:
        return

    valor_cp = _to_dec(row.get("rec_ho"))
    if valor_cp is None:
        rep.aviso(f"tb_contapagar id={row['id']} ignorado: valor zerado ou invalido.")
        return

    try:
        pgo_dt = row.get("pgo_data") or datetime.now()
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        cc_id = map_costcenter_by_id_cob(row.get("credor_id") or row.get("credor_sigla")) or cc_padrao
        if exigir_cc and not cc_id:
            rep.aviso(f"tb_contapagar id={row['id']} pulado: credor sem centro de custo mapeado.")
            return

        vcto = vcto_mais_15(pgo_dt)
        obs = _last_con_obs_by_pgo(row.get("pgo_id"))
        desc = _desc(row.get("filial_nome"), obs)
        categoria = _categoria_cp_out_contapagar(row)
        vb_code = vb_code_only(row.get("credor_id"), row.get("filial_nome"))
        if vb_code:
            desc = f"{desc} {vb_code}"
        reference = str(row.get("ope_nome") or "").strip() or str(row.get("co_id") or "")

        if dry_run:
            rep.processados += 1
            return

        cliente_nome = row.get("cliente_nome") or "Sem Nome"
        cliente_doc = only_digits(row.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_fornecedor = find_or_create_supplier(cliente_nome, cliente_doc)

        send_payment(
            stakeholder_id=stakeholder_fornecedor,
            vcto=vcto, desc=desc, reference=reference,
            category_id=categoria, value=valor_cp, costcenter_id=cc_id,
        )
        _marcar_enviado(TB["contapagar"], row["id"])
        rep.processados += 1
    except Exception as e:
        rep.erro(f"tb_contapagar id={row['id']} falhou: {e}")


def processar_contareceber(_id, account_id, cc_padrao, rep, *, exigir_cc=False, dry_run=False):
    row = get_by_id(TB["contareceber"], _id)
    if not row:
        return

    valor_cr = _to_dec(row.get("rec_ho"))
    if valor_cr is None:
        rep.aviso(f"tb_contareceber id={row['id']} ignorado: valor zerado ou invalido.")
        return

    try:
        pgo_dt = row.get("pgo_data") or datetime.now()
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        cc_id = map_costcenter_by_id_cob(row.get("credor_id") or row.get("credor_sigla")) or cc_padrao
        if exigir_cc and not cc_id:
            rep.aviso(f"tb_contareceber id={row['id']} pulado: credor sem centro de custo mapeado.")
            return

        dt_str = pgo_dt.strftime("%Y-%m-%d")
        obs = _last_con_obs_by_pgo(row.get("pgo_id"))
        desc = _desc(row.get("filial_nome"), obs)
        categoria = _categoria_cr_in_contareceber(row)
        vb_code = vb_code_only(row.get("credor_id"), row.get("filial_nome"))
        if vb_code:
            desc = f"{desc} {vb_code}"
        reference = str(row.get("ope_nome") or "").strip() or str(row.get("co_id") or "")

        if dry_run:
            rep.processados += 1
            return

        cliente_nome = row.get("cliente_nome") or "Sem Nome"
        cliente_doc = only_digits(row.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_cliente = find_or_create_customer(cliente_nome, cliente_doc)

        send_receipt(
            account_id,
            stakeholder_id=stakeholder_cliente,
            dt=dt_str, desc=desc, reference=reference,
            category_id=categoria, value=valor_cr, costcenter_id=cc_id,
        )
        _marcar_enviado(TB["contareceber"], row["id"])
        rep.processados += 1
    except Exception as e:
        rep.erro(f"tb_contareceber id={row['id']} falhou: {e}")


def processar_despesa(_id, account_id, cc_padrao, rep, *, exigir_cc=False, dry_run=False):
    row = get_by_id(TB["despesa"], _id)
    if not row:
        return

    valor_des = _to_dec(row.get("des_valor"))
    if valor_des is None:
        rep.aviso(f"tb_despesa id={row['id']} ignorado: valor zerado ou invalido.")
        return

    base = load_repasse_base_by_aco(row["aco_id"])
    if not base:
        rep.erro(f"tb_despesa id={row['id']} (acordo {row['aco_id']}) sem vinculo em tb_repassevr; nao enviado.")
        return

    try:
        pgo_dt = base.get("pgo_data")
        if not pgo_dt:
            rep.erro(f"tb_despesa id={row['id']} (acordo {row['aco_id']}) sem data no repasseVR; nao enviado.")
            return
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        cc_id = map_costcenter_by_id_cob(base.get("credor_id") or base.get("credor_sigla")) or cc_padrao
        if exigir_cc and not cc_id:
            rep.aviso(f"tb_despesa id={row['id']} (acordo {row['aco_id']}) pulado: credor sem centro de custo mapeado.")
            return

        dt_str = pgo_dt.strftime("%Y-%m-%d")
        desc = _desc(base.get("filial_nome"), base.get("con_obs"))
        aco_id = row.get("aco_id")
        vb_code = vb_code_only(base.get("credor_id"), base.get("filial_nome"))
        is_vb = bool(vb_code)
        if is_vb:
            desc = f"{desc} {vb_code}"
        reference = str(base.get("ope_nome") or "").strip() or str(aco_id or "")
        cliente_nome = base.get("cliente_nome") or "Sem Nome"

        if dry_run:
            rep.processados += 1
            return

        cliente_doc = only_digits(base.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_cliente = find_or_create_customer(cliente_nome, cliente_doc)
        stakeholder_fornecedor = find_or_create_supplier(cliente_nome, cliente_doc)

        send_receipt(
            account_id,
            stakeholder_id=stakeholder_cliente,
            dt=dt_str, desc=desc, reference=reference,
            category_id=CAT["REEMBOLSOS_IN"], value=valor_des, costcenter_id=cc_id,
        )
        vcto = (pgo_dt.date() + timedelta(days=15)).strftime("%Y-%m-%d")
        desc_pay = desc if is_vb else f"Despesa {aco_id} - {cliente_nome}"
        send_payment(
            stakeholder_id=stakeholder_fornecedor,
            vcto=vcto, desc=desc_pay, reference=reference,
            category_id=CAT["GASTOS_REEMBOLSAVEIS_OUT"], value=valor_des, costcenter_id=cc_id,
        )
        _marcar_enviado(TB["despesa"], row["id"])
        rep.processados += 1
    except Exception as e:
        rep.erro(f"tb_despesa id={row['id']} falhou: {e}")


# Mapa tabela -> (processador, coluna de data)
PROCESSADORES = [
    ("repasse", processar_repasse),
    ("repassevr", processar_repassevr),
    ("contapagar", processar_contapagar),
    ("contareceber", processar_contareceber),
    ("despesa", processar_despesa),
]


def _ids_nao_enviados_por_data(table_key, data_ini, data_fim):
    """
    IDs de registros com enviado=FALSE cuja data efetiva cai em [ini, fim].

    A maioria das tabelas usa a coluna pgo_data. tb_despesa NAO tem pgo_data:
    a data dela vem do repasse/repasseVR vinculado (mesma regra da listagem),
    com fallback em aco_etl_alteracao.
    """
    table = TB[table_key]
    pk = PK_COL[table]

    if table_key == "despesa":
        data_expr = "COALESCE(r.pgo_data, rv.pgo_data, d.aco_etl_alteracao)"
        sql = f"""
            SELECT d.{pk} AS id
              FROM {table} d
              LEFT JOIN LATERAL (
                  SELECT pgo_data FROM tb_repasse r
                   WHERE r.aco_id = d.aco_id
                   ORDER BY COALESCE(r.pgo_data, NOW()) DESC LIMIT 1
              ) r ON TRUE
              LEFT JOIN LATERAL (
                  SELECT pgo_data FROM tb_repassevr rv
                   WHERE rv.aco_id = d.aco_id
                   ORDER BY COALESCE(rv.pgo_data, NOW()) DESC LIMIT 1
              ) rv ON TRUE
             WHERE d.enviado = FALSE
               AND DATE({data_expr}) >= %s
               AND DATE({data_expr}) <= %s
             ORDER BY d.{pk}
        """
        return [r["id"] for r in qfetchall(sql, [data_ini, data_fim])]

    sql = f"""
        SELECT {pk} AS id
          FROM {table}
         WHERE enviado = FALSE
           AND DATE(pgo_data) >= %s
           AND DATE(pgo_data) <= %s
         ORDER BY {pk}
    """
    return [r["id"] for r in qfetchall(sql, [data_ini, data_fim])]


def enviar_periodo(data_ini, data_fim, *, dry_run=False, cc_padrao=None, rep=None):
    """
    Envia para o Nibo todos os registros NAO enviados (enviado=FALSE) cujas
    datas (pgo_data) caem entre data_ini e data_fim, em todas as 5 tabelas.

    Uso automatico: exige centro de custo mapeado (pula quem nao tem).
    """
    account_id = settings.NIBO_ACCOUNT_ID
    rep = rep or RelatorioRemessa()

    for table_key, processar in PROCESSADORES:
        ids = _ids_nao_enviados_por_data(table_key, data_ini, data_fim)
        for _id in ids:
            processar(_id, account_id, cc_padrao, rep, exigir_cc=True, dry_run=dry_run)

    return rep
