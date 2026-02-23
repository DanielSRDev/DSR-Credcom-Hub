#views.py
from django.http import HttpResponseForbidden
from core.permissions import tem_acesso

from datetime import datetime, timedelta, date
import unicodedata

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib import messages
from django.db import connection, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import FiltroForm
from .services.categories_map import CATEGORIES as CAT
from .services.nibo import (
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

def _norm_key(s: str | None) -> str:
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
    _norm_key("Residencial Sao Paulo"): "VB23",  # duplicata intencional ok
    _norm_key("Goianira"): "VB7",
}

def _is_vb_credor(credor_id) -> bool:
    try:
        return int(credor_id) == VB_CREDOR_ID
    except Exception:
        return False

def vb_reference(credor_id, filial_nome, default_reference):
    try:
        if int(credor_id) == VB_CREDOR_ID:
            code = VB_MAP.get(_norm_key((filial_nome or "").strip()))
            if code:
                return code
    except Exception:
        pass
    return default_reference

# ✅ NOVO: helper pra pegar só o código VBxx (ou "" se não achar)
def vb_code_only(credor_id, filial_nome) -> str:
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
}

# ============================================================
# HELPERS SQL
# ============================================================
def qexec(sql: str, params=None) -> int:
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.rowcount

def qfetchall(sql: str, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

def qfetchone(sql: str, params=None):
    rows = qfetchall(sql, params)
    return rows[0] if rows else None

def vcto_mais_15(pgo_data):
    dt = pgo_data if isinstance(pgo_data, datetime) else datetime.combine(pgo_data, datetime.min.time())
    return (dt.date() + timedelta(days=15)).strftime("%Y-%m-%d")

# ============================================================
# HELPERS DE FILTRO
# ============================================================
def _filtro_enviado_fragment(enviado: str) -> str:
    if enviado == "sim":
        return " AND enviado = TRUE "
    if enviado == "nao":
        return " AND enviado = FALSE "
    return ""

def _filtro_data_fragment(data_ini, data_fim, col="pgo_data"):
    frag, params = "", []
    if data_ini:
        frag += f" AND DATE({col}) >= %s "; params.append(data_ini)
    if data_fim:
        frag += f" AND DATE({col}) <= %s "; params.append(data_fim)
    return frag, params

def _all_credor_siglas() -> list[str]:
    sql = """
        SELECT DISTINCT credor_sigla FROM tb_repasse      WHERE credor_sigla IS NOT NULL
        UNION
        SELECT DISTINCT credor_sigla FROM tb_repassevr    WHERE credor_sigla IS NOT NULL
        UNION
        SELECT DISTINCT credor_sigla FROM tb_contareceber WHERE credor_sigla IS NOT NULL
        UNION
        SELECT DISTINCT credor_sigla FROM tb_contaspagar  WHERE credor_sigla IS NOT NULL
        ORDER BY 1
    """
    rows = qfetchall(sql, [])
    return [r["credor_sigla"] for r in rows]

def _in_clause(col: str, values: list[str]) -> tuple[str, list]:
    vals = [(v or "").upper() for v in values if v]
    if not vals:
        return "", []
    placeholders = ", ".join(["%s"] * len(vals))
    frag = f" UPPER(COALESCE({col},'')) IN ({placeholders}) "
    return frag, vals

def _filtro_credores(col: str, credores: list[str] | None) -> tuple[str, list]:
    if not credores:
        return "", []
    frag, p = _in_clause(col, credores)
    return " AND " + frag, p

def _filtro_credores_despesa(credores: list[str] | None) -> tuple[str, list]:
    if not credores:
        return "", []
    frag_r, p1 = _in_clause("r.credor_sigla", credores)
    frag_v, p2 = _in_clause("rv.credor_sigla", credores)
    return f" AND ({frag_r} OR {frag_v}) ", (p1 + p2)

def _last_con_obs_by_pgo(pgo_id: int | None) -> str | None:
    """
    Busca o con_obs mais recente para um pgo_id,
    primeiro em tb_repasse; se não achar, tenta em tb_repassevr.
    """
    if not pgo_id:
        return None

    r = qfetchone(
        """
        SELECT con_obs
          FROM tb_repasse
         WHERE pgo_id = %s
         ORDER BY COALESCE(pgo_data, NOW()) DESC
         LIMIT 1
        """,
        [pgo_id],
    )
    if r and r.get("con_obs"):
        return r["con_obs"]

    rv = qfetchone(
        """
        SELECT con_obs
          FROM tb_repassevr
         WHERE pgo_id = %s
         ORDER BY COALESCE(pgo_data, NOW()) DESC
         LIMIT 1
        """,
        [pgo_id],
    )
    return rv["con_obs"] if rv and rv.get("con_obs") else None

# ============================================================
# LISTAGENS (somente leitura)
# ============================================================
def listar_repasse(data_ini, data_fim, cliente, credores, enviado):
    table = TB["repasse"]
    where, params = " WHERE 1=1 ", []
    frag, p = _filtro_data_fragment(data_ini, data_fim, "pgo_data"); where += frag; params += p
    if cliente:
        where += " AND cliente_nome ILIKE %s "; params.append(f"%{cliente}%")
    frag, p = _filtro_credores("credor_sigla", credores); where += frag; params += p
    where += _filtro_enviado_fragment(enviado)
    sql = f"""
        SELECT {PK_COL[table]} AS id,
               aco_id, pgo_data, cliente_nome, cliente_cpfcnpj,
               credor_sigla, filial_nome, con_obs, vlr_repasse, enviado,
               credor_id,
               ope_nome
          FROM {table}
        {where}
        ORDER BY COALESCE(pgo_data, NOW()) DESC, {PK_COL[table]} DESC
    """
    return qfetchall(sql, params)

def listar_repassevr(data_ini, data_fim, cliente, credores, enviado):
    table = TB["repassevr"]
    where, params = " WHERE 1=1 ", []
    frag, p = _filtro_data_fragment(data_ini, data_fim, "pgo_data"); where += frag; params += p
    if cliente:
        where += " AND cliente_nome ILIKE %s "; params.append(f"%{cliente}%")
    frag, p = _filtro_credores("credor_sigla", credores); where += frag; params += p
    where += _filtro_enviado_fragment(enviado)
    sql = f"""
        SELECT {PK_COL[table]} AS id,
               aco_id, pgo_data, cliente_nome, cliente_cpfcnpj,
               credor_sigla, filial_nome, con_obs, vlr_repasse, enviado,
               credor_id,
               ope_nome
          FROM {table}
        {where}
        ORDER BY COALESCE(pgo_data, NOW()) DESC, {PK_COL[table]} DESC
    """
    return qfetchall(sql, params)

def listar_despesa(data_ini, data_fim, cliente, credores, enviado):
    # mesma expressão usada para exibir a data:
    data_expr = "COALESCE(r.pgo_data, rv.pgo_data, d.aco_etl_alteracao)"

    where, params = " WHERE 1=1 ", []

    frag, p = _filtro_data_fragment(data_ini, data_fim, data_expr)
    where += frag; params += p

    if cliente:
        where += " AND (r.cliente_nome ILIKE %s OR rv.cliente_nome ILIKE %s OR d.dtp_nome ILIKE %s) "
        params += [f"%{cliente}%"] * 3

    frag, p = _filtro_credores_despesa(credores); where += frag; params += p

    where += _filtro_enviado_fragment(enviado).replace(" AND ", " AND d.")

    sql = f"""
        SELECT d.des_id_local AS id,
               d.aco_id,
               {data_expr}                                        AS pgo_data,
               COALESCE(r.cliente_nome,  rv.cliente_nome)          AS cliente_nome,
               COALESCE(r.cliente_cpfcnpj, rv.cliente_cpfcnpj)     AS cliente_cpfcnpj,
               COALESCE(r.credor_sigla,  rv.credor_sigla)          AS credor_sigla,
               COALESCE(r.filial_nome,   rv.filial_nome)           AS filial_nome,
               COALESCE(r.con_obs,       rv.con_obs, d.dtp_nome)   AS con_obs,
               d.des_valor,
               d.enviado,
               COALESCE(r.credor_id, rv.credor_id)                 AS credor_id,
               COALESCE(r.ope_nome, rv.ope_nome)                   AS ope_nome
          FROM tb_despesa d
          LEFT JOIN LATERAL (
              SELECT pgo_data, cliente_nome, cliente_cpfcnpj, credor_sigla, filial_nome,
                     con_obs, credor_id, ope_nome
                FROM tb_repasse r
               WHERE r.aco_id = d.aco_id
               ORDER BY COALESCE(r.pgo_data, NOW()) DESC
               LIMIT 1
          ) r ON TRUE
          LEFT JOIN LATERAL (
              SELECT pgo_data, cliente_nome, cliente_cpfcnpj, credor_sigla, filial_nome,
                     con_obs, credor_id, ope_nome
                FROM tb_repassevr rv
               WHERE rv.aco_id = d.aco_id
               ORDER BY COALESCE(rv.pgo_data, NOW()) DESC
               LIMIT 1
          ) rv ON TRUE
        {where}
        ORDER BY {data_expr} DESC, d.des_id_local DESC
    """
    return qfetchall(sql, params)

def listar_contareceber(data_ini, data_fim, cliente, credores, enviado):
    table = TB["contareceber"]
    where, params = " WHERE 1=1 ", []
    frag, p = _filtro_data_fragment(data_ini, data_fim, "pgo_data"); where += frag; params += p
    if cliente:
        where += " AND cliente_nome ILIKE %s "; params.append(f"%{cliente}%")
    frag, p = _filtro_credores("credor_sigla", credores); where += frag; params += p
    where += _filtro_enviado_fragment(enviado)

    sql = f"""
        SELECT {PK_COL[table]} AS id,
               co_id, pgo_data, cliente_nome, cliente_cpfcnpj,
               credor_sigla, filial_nome,
               COALESCE(r.con_obs, rv.con_obs)::text AS con_obs,
               rec_ho, enviado, credor_id,
               rec_atraso, dup,
               ope_nome
          FROM {table}
          LEFT JOIN LATERAL (
              SELECT con_obs
                FROM tb_repasse r
               WHERE r.pgo_id = {table}.pgo_id
               ORDER BY COALESCE(r.pgo_data, NOW()) DESC
               LIMIT 1
          ) r ON TRUE
          LEFT JOIN LATERAL (
              SELECT con_obs
                FROM tb_repassevr rv
               WHERE rv.pgo_id = {table}.pgo_id
               ORDER BY COALESCE(rv.pgo_data, NOW()) DESC
               LIMIT 1
          ) rv ON TRUE
        {where}
        ORDER BY COALESCE(pgo_data, NOW()) DESC, {PK_COL[table]} DESC
    """
    return qfetchall(sql, params)

def listar_contapagar(data_ini, data_fim, cliente, credores, enviado):
    table = TB["contapagar"]
    where, params = " WHERE 1=1 ", []
    frag, p = _filtro_data_fragment(data_ini, data_fim, "pgo_data"); where += frag; params += p
    if cliente:
        where += " AND cliente_nome ILIKE %s "; params.append(f"%{cliente}%")
    frag, p = _filtro_credores("credor_sigla", credores); where += frag; params += p
    where += _filtro_enviado_fragment(enviado)

    sql = f"""
        SELECT {PK_COL[table]} AS id,
               co_id, pgo_data, cliente_nome, cliente_cpfcnpj,
               credor_sigla, filial_nome,
               COALESCE(r.con_obs, rv.con_obs)::text AS con_obs,
               rec_ho, enviado, credor_id, rec_atraso,
               ope_nome
          FROM {table}
          LEFT JOIN LATERAL (
              SELECT con_obs
                FROM tb_repasse r
               WHERE r.pgo_id = {table}.pgo_id
               ORDER BY COALESCE(r.pgo_data, NOW()) DESC
               LIMIT 1
          ) r ON TRUE
          LEFT JOIN LATERAL (
              SELECT con_obs
                FROM tb_repassevr rv
               WHERE rv.pgo_id = {table}.pgo_id
               ORDER BY COALESCE(rv.pgo_data, NOW()) DESC
               LIMIT 1
          ) rv ON TRUE
        {where}
        ORDER BY COALESCE(pgo_data, NOW()) DESC, {PK_COL[table]} DESC
    """
    return qfetchall(sql, params)

# ============================================================
# HELPERS DE REGRA / DESCRIÇÃO / NORMALIZAÇÃO
# ============================================================
def _desc(filial: str | None, obs: str | None) -> str:
    filial = (filial or "").strip()
    obs    = (obs or "").strip()
    if filial and obs:
        return f"{filial} + {obs}"
    return filial or obs or ""

def _norm_filial(name: str | None) -> str:
    return (name or "").strip().upper()

def _categoria_cr_in_contareceber(row: dict) -> str:
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

def _categoria_cp_out_contapagar(row: dict) -> str:
    credor_id = row.get("credor_id")
    atraso = row.get("rec_atraso") or 0
    filial_u = _norm_filial(row.get("filial_nome"))
    if credor_id == AM3_CREDOR_ID and atraso > 120:
        return CAT["HON_50_50_OUT"] if filial_u in FILIAIS_50 else CAT["HON_60_40_OUT"]
    return CAT["REPASSES_OUT"]

def _min_receipt_date() -> date | None:
    s = getattr(settings, "NIBO_ACCOUNT_MIN_DATE", None)
    if s:
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            pass
    return None

# ============================================================
# VIEW DO PAINEL
# ============================================================
@login_required
def painel(request):
    if not tem_acesso(request.user, "NIBO"):
        return HttpResponseForbidden("Você não tem acesso ao módulo Nibo.")
    credor_choices = _all_credor_siglas()
    form = FiltroForm(request.GET or None, credor_choices=credor_choices)

    di = df = cli = enviado = None
    credores: list[str] = []

    if form.is_valid():
        di        = form.cleaned_data.get("data_ini")
        df        = form.cleaned_data.get("data_fim")
        cli       = form.cleaned_data.get("cliente")
        credores  = form.cleaned_data.get("credores") or []
        enviado   = form.cleaned_data.get("enviado")

    repasse      = listar_repasse(di, df, cli, credores, enviado)
    repassevr    = listar_repassevr(di, df, cli, credores, enviado)
    despesa      = listar_despesa(di, df, cli, credores, enviado)
    contareceber = listar_contareceber(di, df, cli, credores, enviado)
    contapagar   = listar_contapagar(di, df, cli, credores, enviado)

    ctx = {
        "form": form,
        "repasse": repasse,
        "repassevr": repassevr,
        "despesa": despesa,
        "contareceber": contareceber,
        "contapagar": contapagar,
    }
    return render(request, "nibo_panel/painel.html", ctx)

# ============================================================
# ENVIO — BLOCOS SEPARADOS POR TABELA
# ============================================================
@login_required
@require_POST
@transaction.atomic
def enviar_remessa(request):
    if not tem_acesso(request.user, "NIBO"):
        return HttpResponseForbidden("Você não tem acesso ao módulo Nibo.")
    account_id = settings.NIBO_ACCOUNT_ID

    ids_repasse      = [int(x) for x in request.POST.getlist("repasse_ids")]
    ids_repassevr    = [int(x) for x in request.POST.getlist("repassevr_ids")]
    ids_contapagar   = [int(x) for x in request.POST.getlist("contapagar_ids")]
    ids_contareceber = [int(x) for x in request.POST.getlist("contareceber_ids")]
    ids_despesa      = [int(x) for x in request.POST.getlist("despesa_ids")]

    CC_PADRAO = request.POST.get("cc_padrao") or None
    processados = 0

    def get_by_id(table: str, _id: int):
        pk = PK_COL[table]
        row = qfetchone(f"SELECT * FROM {table} WHERE {pk} = %s", [_id])
        if row:
            row["id"] = row[pk]
        return row

    def load_repasse_base_by_aco(aco_id: int):
        """
        Busca dados de referência: tenta repasseVR primeiro.
        Se não existir, busca repasse normal.
        """
        # 1) tenta VR
        vr = qfetchone(
            """
            SELECT pgo_data, cliente_nome, cliente_cpfcnpj, credor_sigla,
                filial_nome, con_obs, credor_id, vlr_repasse,
                ope_nome
            FROM tb_repassevr
            WHERE aco_id = %s
            ORDER BY COALESCE(pgo_data, NOW()) DESC
            LIMIT 1
            """,
            [aco_id],
        )
        if vr:
            return vr

        # 2) fallback: tenta repasse normal
        rep = qfetchone(
            """
            SELECT pgo_data, cliente_nome, cliente_cpfcnpj, credor_sigla,
                filial_nome, con_obs, credor_id, vlr_repasse,
                ope_nome
            FROM tb_repasse
            WHERE aco_id = %s
            ORDER BY COALESCE(pgo_data, NOW()) DESC
            LIMIT 1
            """,
            [aco_id],
        )
        return rep

    def send_receipt(*, stakeholder_id, dt, desc, reference, category_id, value, costcenter_id):
        return create_receipt_paid(
            account_id=account_id,
            stakeholder_id=stakeholder_id,
            dt=dt, desc=desc, reference=reference,
            category_id=category_id, value=float(value or 0),
            costcenter_id=costcenter_id, accrual_date=dt, flag=False,
        )

    def send_payment(*, stakeholder_id, vcto, desc, reference, category_id, value, costcenter_id):
        return create_payment_scheduled(
            stakeholder_id=stakeholder_id,
            dt=vcto, desc=desc, reference=reference,
            category_id=category_id, value=float(value or 0),
            costcenter_id=costcenter_id, accrual_date=vcto,
        )

    # ----------- tb_repasse -----------
    for _id in ids_repasse:
        row = get_by_id(TB["repasse"], _id)
        if not row:
            continue

        pgo_dt = row.get("pgo_data") or datetime.now()
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        min_dt = _min_receipt_date()
        send_dt = pgo_dt.date()
        if min_dt and send_dt < min_dt:
            send_dt = min_dt
            messages.warning(
                request,
                f"tb_repasse id={row['id']} (acordo {row.get('aco_id')}) com data {pgo_dt.date()} "
                f"ajustada para {send_dt} (>= saldo inicial da conta)."
            )
        dt_str = send_dt.strftime("%Y-%m-%d")

        cliente_nome = row.get("cliente_nome") or "Sem Nome"
        cliente_doc = only_digits(row.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_cliente = find_or_create_customer(cliente_nome, cliente_doc)
        stakeholder_fornecedor = find_or_create_supplier(cliente_nome, cliente_doc)

        cc_id = map_costcenter_by_id_cob(row.get("credor_id") or row.get("credor_sigla")) or CC_PADRAO
        desc = _desc(row.get("filial_nome"), row.get("con_obs"))

        # >>> MUDOU AQUI: VB vai pra DESCRIÇÃO
        vb_code = vb_code_only(row.get("credor_id"), row.get("filial_nome"))
        if vb_code:
            desc = f"{desc} {vb_code}"

        aco_id = row.get("aco_id")

        # >>> MUDOU AQUI: referência = ope_nome (fallback p/ aco_id)
        reference = str(row.get("ope_nome") or "").strip()
        if not reference:
            reference = str(aco_id or "")

        send_receipt(
            stakeholder_id=stakeholder_cliente,
            dt=dt_str, desc=desc, reference=reference,
            category_id=CAT["REPASSES_IN"], value=row.get("vlr_repasse"),
            costcenter_id=cc_id,
        )
        vcto = vcto_mais_15(pgo_dt)
        send_payment(
            stakeholder_id=stakeholder_fornecedor,
            vcto=vcto, desc=desc, reference=reference,
            category_id=CAT["REPASSES_OUT"], value=row.get("vlr_repasse"),
            costcenter_id=cc_id,
        )

        qexec(f"UPDATE {TB['repasse']} SET enviado = TRUE WHERE {PK_COL[TB['repasse']]} = %s", [row["id"]])
        processados += 1

    # ----------- tb_repassevr -----------
    from decimal import Decimal, ROUND_HALF_UP
    for _id in ids_repassevr:
        row = get_by_id(TB["repassevr"], _id)
        if not row:
            continue
        if row.get("enviado") is True:
            messages.info(request, f"tb_repassevr id={row['id']} já enviado. Ignorado.")
            continue

        try:
            valor_dec = Decimal(str(row.get("vlr_repasse") or 0)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except Exception:
            valor_dec = Decimal("0.00")
        if valor_dec < Decimal("0.01"):
            messages.warning(request, f"tb_repassevr id={row.get('id')} ignorado: valor < 0,01.")
            continue

        pgo_dt = row.get("pgo_data") or datetime.now()
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        dt_str = pgo_dt.strftime("%Y-%m-%d")
        vcto   = (pgo_dt.date() + timedelta(days=15)).strftime("%Y-%m-%d")

        cliente_nome = row.get("cliente_nome") or "Sem Nome"
        cliente_doc  = only_digits(row.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_cliente    = find_or_create_customer(cliente_nome, cliente_doc)
        stakeholder_fornecedor = find_or_create_supplier(cliente_nome, cliente_doc)

        cc_id = map_costcenter_by_id_cob(row.get("credor_id") or row.get("credor_sigla")) or CC_PADRAO
        aco_id = row.get("aco_id")
        desc   = _desc(row.get("filial_nome"), row.get("con_obs"))

        # >>> MUDOU AQUI: VB vai pra DESCRIÇÃO
        vb_code = vb_code_only(row.get("credor_id"), row.get("filial_nome"))
        is_vb = bool(vb_code)
        if is_vb:
            desc = f"{desc} {vb_code}"

        # >>> MUDOU AQUI: referência = ope_nome (fallback p/ aco_id)
        reference = str(row.get("ope_nome") or "").strip()
        if not reference:
            reference = str(aco_id or "")

        send_receipt(
            stakeholder_id=stakeholder_cliente,
            dt=dt_str, desc=desc, reference=reference,
            category_id=CAT["REPASSES_IN"], value=float(valor_dec),
            costcenter_id=cc_id,
        )

        # mantém sua descrição antiga pros não-VB; pro VB usa a descrição padrão (filial+obs+VB)
        desc_pay = desc if is_vb else f"Repasse {aco_id} - {cliente_nome}"

        send_payment(
            stakeholder_id=stakeholder_fornecedor,
            vcto=vcto, desc=desc_pay,
            reference=reference, category_id=CAT["REPASSES_OUT"],
            value=float(valor_dec), costcenter_id=cc_id,
        )

        qexec(f"UPDATE {TB['repassevr']} SET enviado = TRUE WHERE {PK_COL[TB['repassevr']]} = %s", [row["id"]])
        processados += 1

    # ----------- tb_contapagar -----------
    for _id in ids_contapagar:
        row = get_by_id(TB["contapagar"], _id)
        if not row:
            continue

        pgo_dt = row.get("pgo_data") or datetime.now()
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        cliente_nome = row.get("cliente_nome") or "Sem Nome"
        cliente_doc  = only_digits(row.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_fornecedor = find_or_create_supplier(cliente_nome, cliente_doc)

        cc_id = map_costcenter_by_id_cob(row.get("credor_id") or row.get("credor_sigla")) or CC_PADRAO
        vcto  = vcto_mais_15(pgo_dt)
        obs   = _last_con_obs_by_pgo(row.get("pgo_id"))
        desc  = _desc(row.get("filial_nome"), obs)
        categoria = _categoria_cp_out_contapagar(row)

        # >>> MUDOU AQUI: VB vai pra DESCRIÇÃO
        vb_code = vb_code_only(row.get("credor_id"), row.get("filial_nome"))
        if vb_code:
            desc = f"{desc} {vb_code}"

        # >>> MUDOU AQUI: referência = ope_nome (fallback p/ co_id)
        ref_default = str(row.get("co_id") or "")
        reference = str(row.get("ope_nome") or "").strip()
        if not reference:
            reference = ref_default

        send_payment(
            stakeholder_id=stakeholder_fornecedor,
            vcto=vcto, desc=desc, reference=reference,
            category_id=categoria, value=row.get("rec_ho"),
            costcenter_id=cc_id,
        )
        qexec(f"UPDATE {TB['contapagar']} SET enviado = TRUE WHERE {PK_COL[TB['contapagar']]} = %s", [row["id"]])
        processados += 1

    # ----------- tb_contareceber -----------
    for _id in ids_contareceber:
        row = get_by_id(TB["contareceber"], _id)
        if not row:
            continue

        pgo_dt = row.get("pgo_data") or datetime.now()
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        cliente_nome = row.get("cliente_nome") or "Sem Nome"
        cliente_doc  = only_digits(row.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_cliente = find_or_create_customer(cliente_nome, cliente_doc)

        cc_id    = map_costcenter_by_id_cob(row.get("credor_id") or row.get("credor_sigla")) or CC_PADRAO
        dt_str   = pgo_dt.strftime("%Y-%m-%d")
        obs = _last_con_obs_by_pgo(row.get("pgo_id"))
        desc = _desc(row.get("filial_nome"), obs)
        categoria = _categoria_cr_in_contareceber(row)

        # >>> MUDOU AQUI: VB vai pra DESCRIÇÃO
        vb_code = vb_code_only(row.get("credor_id"), row.get("filial_nome"))
        if vb_code:
            desc = f"{desc} {vb_code}"

        # >>> MUDOU AQUI: referência = ope_nome (fallback p/ co_id)
        ref_default = str(row.get("co_id") or "")
        reference = str(row.get("ope_nome") or "").strip()
        if not reference:
            reference = ref_default

        send_receipt(
            stakeholder_id=stakeholder_cliente,
            dt=dt_str, desc=desc, reference=reference,
            category_id=categoria, value=row.get("rec_ho"),
            costcenter_id=cc_id,
        )
        qexec(f"UPDATE {TB['contareceber']} SET enviado = TRUE WHERE {PK_COL[TB['contareceber']]} = %s", [row["id"]])
        processados += 1

    # ----------- tb_despesa -----------
    for _id in ids_despesa:
        row = get_by_id(TB["despesa"], _id)
        if not row:
            continue

        base = load_repasse_base_by_aco(row["aco_id"])
        if not base:
            messages.error(
                request,
                f"tb_despesa id={row['id']} (acordo {row['aco_id']}) sem vínculo em tb_repassevr; não enviado."
            )
            continue

        pgo_dt = base.get("pgo_data")
        if not pgo_dt:
            messages.error(
                request,
                f"tb_despesa id={row['id']} (acordo {row['aco_id']}) sem data no repasseVR; não enviado."
            )
            continue
        if not isinstance(pgo_dt, datetime):
            pgo_dt = datetime.combine(pgo_dt, datetime.min.time())

        cliente_nome = base.get("cliente_nome") or "Sem Nome"
        cliente_doc  = only_digits(base.get("cliente_cpfcnpj") or "00000000000")
        stakeholder_cliente    = find_or_create_customer(cliente_nome, cliente_doc)
        stakeholder_fornecedor = find_or_create_supplier(cliente_nome, cliente_doc)

        cc_id  = map_costcenter_by_id_cob(base.get("credor_id") or base.get("credor_sigla")) or CC_PADRAO
        dt_str = pgo_dt.strftime("%Y-%m-%d")
        desc   = _desc(base.get("filial_nome"), base.get("con_obs"))
        aco_id = row.get("aco_id")
        valor  = row.get("des_valor")

        # >>> MUDOU AQUI: VB vai pra DESCRIÇÃO
        vb_code = vb_code_only(base.get("credor_id"), base.get("filial_nome"))
        is_vb = bool(vb_code)
        if is_vb:
            desc = f"{desc} {vb_code}"

        # >>> MUDOU AQUI: referência = ope_nome (fallback p/ aco_id)
        reference = str(base.get("ope_nome") or "").strip()
        if not reference:
            reference = str(aco_id or "")

        send_receipt(
            stakeholder_id=stakeholder_cliente,
            dt=dt_str, desc=desc, reference=reference,
            category_id=CAT["REEMBOLSOS_IN"], value=valor,
            costcenter_id=cc_id,
        )
        vcto = (pgo_dt.date() + timedelta(days=15)).strftime("%Y-%m-%d")

        desc_pay = desc if is_vb else f"Despesa {aco_id} - {cliente_nome}"

        send_payment(
            stakeholder_id=stakeholder_fornecedor,
            vcto=vcto, desc=desc_pay,
            reference=reference, category_id=CAT["GASTOS_REEMBOLSAVEIS_OUT"],
            value=valor, costcenter_id=cc_id,
        )

        qexec(f"UPDATE {TB['despesa']} SET enviado = TRUE WHERE {PK_COL[TB['despesa']]} = %s", [row["id"]])
        processados += 1

    messages.success(request, f"Remessa enviada. Registros processados: {processados}.")
    return redirect("nibo_panel:painel")
