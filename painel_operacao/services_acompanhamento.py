from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum

from .models import (
    CarteiraSupervisor,
    MetaOperadorCarteira,
    PainelConfiguracao,
    PainelOperacaoRelatorioGeral,
    SupervisorPainel,
)


ZERO = Decimal("0.00")


def decimal_or_zero(value):
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def normalizar_texto(value):
    return str(value or "").strip().lower()


def somar_decimal(qs, campo):
    return decimal_or_zero(qs.aggregate(total=Sum(campo))["total"])


def percentual(valor, total):
    valor = decimal_or_zero(valor)
    total = decimal_or_zero(total)

    if total <= 0:
        return Decimal("0.00")

    return ((valor / total) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def limitar_percentual_css(valor):
    valor = decimal_or_zero(valor)
    if valor < 0:
        return Decimal("0.00")
    if valor > 100:
        return Decimal("100.00")
    return valor


def classe_percentual_meta(pct):
    pct = decimal_or_zero(pct)
    if pct >= 100:
        return "meta-batida"
    if pct >= 80:
        return "meta-quase"
    if pct >= 50:
        return "meta-andamento"
    return "meta-baixa"


def linked_credores_ids():
    return list(
        CarteiraSupervisor.objects
        .filter(ativo=True, supervisor__ativo=True)
        .exclude(cre_id__isnull=True)
        .values_list("cre_id", flat=True)
    )


def qs_relatorio_vinculado():
    return PainelOperacaoRelatorioGeral.objects.all()


def aplicar_filtros_relatorio(data_ini=None, data_fim=None, supervisor=None, operador=None, credor=None):
    qs = qs_relatorio_vinculado()

    if data_ini:
        qs = qs.filter(data_referencia__gte=data_ini)
    if data_fim:
        qs = qs.filter(data_referencia__lte=data_fim)
    if supervisor:
        qs = qs.filter(supervisor_nome=supervisor.nome)
    if operador:
        qs = qs.filter(emitido_por_nome=operador)
    if credor:
        qs = qs.filter(credor=credor)

    return qs


def aplicar_filtros_metas(ano, mes, supervisor=None, operador=None, credor=None):
    qs = MetaOperadorCarteira.objects.select_related("carteira", "carteira__supervisor").filter(
        ano=ano,
        mes=mes,
        ativo=True,
    )

    if supervisor:
        qs = qs.filter(carteira__supervisor=supervisor)
    if operador:
        qs = qs.filter(Q(operador_nome=operador) | Q(operador_login=operador))
    if credor:
        qs = qs.filter(carteira__credor_nome=credor)

    return qs


def montar_mapas_meta(metas_qs):
    meta_por_operador = defaultdict(Decimal)
    meta_por_supervisor = defaultdict(Decimal)
    meta_por_operador_carteira = defaultdict(Decimal)

    for meta in metas_qs:
        valor = decimal_or_zero(meta.meta_mensal)
        operador_nome = meta.operador_nome or "SEM OPERADOR"
        operador_login = meta.operador_login or ""
        supervisor_nome = meta.carteira.supervisor.nome if meta.carteira and meta.carteira.supervisor else "SEM SUPERVISOR"
        cre_id = meta.carteira.cre_id if meta.carteira else None
        credor_nome = meta.carteira.credor_nome if meta.carteira else "SEM CARTEIRA"

        meta_por_operador[normalizar_texto(operador_nome)] += valor
        if operador_login:
            meta_por_operador[normalizar_texto(operador_login)] += valor

        meta_por_supervisor[supervisor_nome] += valor
        meta_por_operador_carteira[(normalizar_texto(operador_nome), cre_id)] += valor
        if operador_login:
            meta_por_operador_carteira[(normalizar_texto(operador_login), cre_id)] += valor

    return {
        "operador": meta_por_operador,
        "supervisor": meta_por_supervisor,
        "operador_carteira": meta_por_operador_carteira,
    }


def somar_linha_em_grupo(destino, registro):
    destino["emissao"] += decimal_or_zero(registro.valor_emissao)
    destino["pago"] += decimal_or_zero(registro.valor_pago)
    destino["avencer"] += decimal_or_zero(registro.valor_avencer)
    destino["quebra"] += decimal_or_zero(registro.valor_quebra)
    destino["qtd"] += 1


def calcular_pct_quebra_operador(quebra, pago):
    """% de quebra = quebra / (quebra + pago), retorna como 0-100."""
    quebra = decimal_or_zero(quebra)
    pago = decimal_or_zero(pago)
    base = quebra + pago
    if base <= 0:
        return ZERO
    return ((quebra / base) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_projecao_emissao(meta, pct_quebra):
    """Projeção emissão do mês = (meta * % quebra) + meta."""
    meta = decimal_or_zero(meta)
    pct_quebra = decimal_or_zero(pct_quebra)
    fator = pct_quebra / Decimal("100")
    return (meta * fator + meta).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_meta_do_dia(projecao_emissao, emissao, dias_faltantes):
    """Meta do dia = (projeção emissão - emissão acumulada) / dias faltantes."""
    projecao_emissao = decimal_or_zero(projecao_emissao)
    emissao = decimal_or_zero(emissao)
    if not dias_faltantes or dias_faltantes <= 0:
        return ZERO
    diferenca = projecao_emissao - emissao
    if diferenca <= 0:
        return ZERO
    return (diferenca / Decimal(str(dias_faltantes))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_dias_faltantes(dias_uteis_mes=None, hoje=None):
    """
    Dias úteis faltantes = dias_uteis_mes (config) - dias úteis já decorridos no mês (incluindo hoje).

    Usa o total configurado pelo usuário, não o calendário real do mês.
    Exemplo: dias_uteis_mes=20, hoje=01/jun (segunda) → já_passados=1 → faltantes=19.
    """
    if hoje is None:
        hoje = date.today()
    if not dias_uteis_mes:
        dias_uteis_mes = 22

    inicio_mes = date(hoje.year, hoje.month, 1)
    dia = inicio_mes
    ja_passados = 0
    while dia <= hoje:
        if dia.weekday() < 5:   # seg=0 … sex=4
            ja_passados += 1
        dia += timedelta(days=1)

    return max(0, dias_uteis_mes - ja_passados)


def preparar_metricas_com_meta(item, meta, dias_faltantes=0):
    item["meta"] = decimal_or_zero(meta)
    item["faltante"] = item["meta"] - item["pago"]
    if item["faltante"] < 0:
        item["faltante"] = ZERO

    item["excedente"] = item["pago"] - item["meta"]
    if item["excedente"] < 0:
        item["excedente"] = ZERO

    item["pct_meta"] = percentual(item["pago"], item["meta"])
    item["pct_meta_css"] = format(limitar_percentual_css(item["pct_meta"]), "f")
    item["classe_meta"] = classe_percentual_meta(item["pct_meta"])

    item["pct_quebra"] = calcular_pct_quebra_operador(item["quebra"], item["pago"])
    item["projecao_emissao"] = calcular_projecao_emissao(item["meta"], item["pct_quebra"])
    item["meta_do_dia"] = calcular_meta_do_dia(item["projecao_emissao"], item["emissao"], dias_faltantes)

    return item


def coletar_fora_do_padrao(qs, registered_cre_ids):
    """
    Agrega registros cujo cre_id não está cadastrado em CarteiraSupervisor.

    Retorna lista de dicts: cre_id, credor, emissao, pago, avencer, quebra, qtd.
    """
    grupos = {}
    for registro in qs:
        cre_id = registro.cre_id
        if cre_id is None or cre_id in registered_cre_ids:
            continue
        credor_nome = registro.credor or "SEM NOME"
        chave = (cre_id, credor_nome)
        grupos.setdefault(chave, {
            "cre_id": cre_id,
            "credor": credor_nome,
            "emissao": ZERO,
            "pago": ZERO,
            "avencer": ZERO,
            "quebra": ZERO,
            "qtd": 0,
        })
        grupo = grupos[chave]
        grupo["emissao"] += decimal_or_zero(registro.valor_emissao)
        grupo["pago"] += decimal_or_zero(registro.valor_pago)
        grupo["avencer"] += decimal_or_zero(registro.valor_avencer)
        grupo["quebra"] += decimal_or_zero(registro.valor_quebra)
        grupo["qtd"] += 1

    return sorted(grupos.values(), key=lambda x: x["emissao"], reverse=True)


def montar_acompanhamento_geral(data_ini=None, data_fim=None, supervisor=None, operador=None, credor=None):
    hoje = date.today()
    if data_fim is None:
        data_fim = hoje
    if data_ini is None:
        data_ini = date(data_fim.year, data_fim.month, 1)

    ano_meta = data_fim.year
    mes_meta = data_fim.month

    # Dias úteis do mês vigente a partir da configuração global.
    config = PainelConfiguracao.objects.filter(ativo=True).first()
    dias_uteis_mes = config.dias_uteis_mes if config else 22
    dias_faltantes = calcular_dias_faltantes(dias_uteis_mes)

    # IDs de credores registrados em CarteiraSupervisor ativa.
    registered_cre_ids = set(
        CarteiraSupervisor.objects
        .filter(ativo=True, supervisor__ativo=True)
        .exclude(cre_id__isnull=True)
        .values_list("cre_id", flat=True)
    )

    qs_total = aplicar_filtros_relatorio(
        data_ini=data_ini,
        data_fim=data_fim,
        supervisor=supervisor,
        operador=operador,
        credor=credor,
    ).order_by("emitido_por_nome", "credor", "-data_referencia")

    # Separa registros com carteiras cadastradas dos que estão fora do padrão.
    # Registros fora do padrão são exibidos como alerta mas não somam nas métricas.
    qs = qs_total.filter(cre_id__in=registered_cre_ids) if registered_cre_ids else qs_total.none()
    fora_do_padrao = coletar_fora_do_padrao(qs_total, registered_cre_ids)

    metas_qs = aplicar_filtros_metas(
        ano=ano_meta,
        mes=mes_meta,
        supervisor=supervisor,
        operador=operador,
        credor=credor,
    )

    mapas_meta = montar_mapas_meta(metas_qs)
    meta_geral = decimal_or_zero(metas_qs.aggregate(total=Sum("meta_mensal"))["total"])

    total_emissao = ZERO
    total_pago = ZERO
    total_avencer = ZERO
    total_quebra = ZERO

    operadores = {}
    supervisores = {}
    operador_carteira = {}

    for registro in qs:
        total_emissao += decimal_or_zero(registro.valor_emissao)
        total_pago += decimal_or_zero(registro.valor_pago)
        total_avencer += decimal_or_zero(registro.valor_avencer)
        total_quebra += decimal_or_zero(registro.valor_quebra)

        nome_operador = (registro.emitido_por_nome or "").strip()
        login_operador = (registro.emitido_por_login or "").strip()
        nome_supervisor = (registro.supervisor_nome or "").strip() or "SEM SUPERVISOR"
        cre_id = registro.cre_id
        credor_nome = registro.credor or "SEM CARTEIRA"

        if not nome_operador:
            continue

        chave_operador = (nome_operador, login_operador, nome_supervisor)
        operadores.setdefault(chave_operador, {
            "operador": nome_operador,
            "login": login_operador,
            "supervisor": nome_supervisor,
            "emissao": ZERO,
            "pago": ZERO,
            "avencer": ZERO,
            "quebra": ZERO,
            "qtd": 0,
        })
        somar_linha_em_grupo(operadores[chave_operador], registro)

        supervisores.setdefault(nome_supervisor, {
            "supervisor": nome_supervisor,
            "emissao": ZERO,
            "pago": ZERO,
            "avencer": ZERO,
            "quebra": ZERO,
            "qtd": 0,
        })
        somar_linha_em_grupo(supervisores[nome_supervisor], registro)

        chave_operador_carteira = (nome_operador, login_operador, nome_supervisor, cre_id, credor_nome)
        operador_carteira.setdefault(chave_operador_carteira, {
            "operador": nome_operador,
            "login": login_operador,
            "supervisor": nome_supervisor,
            "cre_id": cre_id,
            "credor": credor_nome,
            "emissao": ZERO,
            "pago": ZERO,
            "avencer": ZERO,
            "quebra": ZERO,
            "qtd": 0,
        })
        somar_linha_em_grupo(operador_carteira[chave_operador_carteira], registro)

    operadores_lista = []
    for item in operadores.values():
        chave_nome = normalizar_texto(item["operador"])
        chave_login = normalizar_texto(item["login"])
        meta = mapas_meta["operador"].get(chave_nome, ZERO)
        if not meta and chave_login:
            meta = mapas_meta["operador"].get(chave_login, ZERO)
        operadores_lista.append(preparar_metricas_com_meta(item, meta, dias_faltantes))

    supervisores_lista = []
    nomes_supervisores = set(supervisores.keys()) | set(mapas_meta["supervisor"].keys())
    for nome in nomes_supervisores:
        item = supervisores.get(nome, {
            "supervisor": nome,
            "emissao": ZERO,
            "pago": ZERO,
            "avencer": ZERO,
            "quebra": ZERO,
            "qtd": 0,
        })
        supervisores_lista.append(preparar_metricas_com_meta(item, mapas_meta["supervisor"].get(nome, ZERO), dias_faltantes))

    operador_carteira_lista = []
    for item in operador_carteira.values():
        chave_nome = normalizar_texto(item["operador"])
        chave_login = normalizar_texto(item["login"])
        cre_id = item["cre_id"]
        meta = mapas_meta["operador_carteira"].get((chave_nome, cre_id), ZERO)
        if not meta and chave_login:
            meta = mapas_meta["operador_carteira"].get((chave_login, cre_id), ZERO)
        operador_carteira_lista.append(preparar_metricas_com_meta(item, meta, dias_faltantes))

    # Também mostra metas cadastradas mesmo quando ainda não existe produção no período.
    chaves_existentes = set()
    for item in operador_carteira_lista:
        chaves_existentes.add((normalizar_texto(item["operador"]), item["cre_id"]))
        if item.get("login"):
            chaves_existentes.add((normalizar_texto(item["login"]), item["cre_id"]))

    for meta in metas_qs:
        cre_id = meta.carteira.cre_id if meta.carteira else None
        chaves_meta = {(normalizar_texto(meta.operador_nome), cre_id)}
        if meta.operador_login:
            chaves_meta.add((normalizar_texto(meta.operador_login), cre_id))

        if chaves_meta & chaves_existentes:
            continue

        operador_nome = (meta.operador_nome or "").strip()
        if not operador_nome:
            continue

        supervisor_nome = meta.carteira.supervisor.nome if meta.carteira and meta.carteira.supervisor else "SEM SUPERVISOR"
        item = {
            "operador": operador_nome,
            "login": meta.operador_login,
            "supervisor": supervisor_nome,
            "cre_id": cre_id,
            "credor": meta.carteira.credor_nome if meta.carteira else "SEM CARTEIRA",
            "emissao": ZERO,
            "pago": ZERO,
            "avencer": ZERO,
            "quebra": ZERO,
            "qtd": 0,
        }
        operador_carteira_lista.append(preparar_metricas_com_meta(item, meta.meta_mensal, dias_faltantes))

    operadores_lista = [
        item for item in operadores_lista
        if (item["operador"] or "").strip() and (item["meta"] > ZERO or item["emissao"] > ZERO or item["pago"] > ZERO or item["avencer"] > ZERO or item["quebra"] > ZERO)
    ]
    supervisores_lista = [
        item for item in supervisores_lista
        if item["supervisor"] != "SEM SUPERVISOR" or (item["meta"] > ZERO or item["emissao"] > ZERO or item["pago"] > ZERO or item["avencer"] > ZERO or item["quebra"] > ZERO)
    ]
    operador_carteira_lista = [
        item for item in operador_carteira_lista
        if (item["operador"] or "").strip() and item["credor"] != "SEM CARTEIRA" and (item["meta"] > ZERO or item["emissao"] > ZERO or item["pago"] > ZERO or item["avencer"] > ZERO or item["quebra"] > ZERO)
    ]

    operadores_lista.sort(key=lambda x: (x["pago"], x["emissao"]), reverse=True)
    supervisores_lista.sort(key=lambda x: (x["pago"], x["emissao"]), reverse=True)
    operador_carteira_lista.sort(key=lambda x: (x["supervisor"], x["operador"], x["credor"]))

    total_status = total_pago + total_avencer + total_quebra
    pct_pago = percentual(total_pago, total_status)
    pct_avencer = percentual(total_avencer, total_status)
    pct_quebra = percentual(total_quebra, total_status)

    faltante_geral = meta_geral - total_pago
    if faltante_geral < 0:
        faltante_geral = ZERO

    excedente_geral = total_pago - meta_geral
    if excedente_geral < 0:
        excedente_geral = ZERO

    pct_meta_geral = percentual(total_pago, meta_geral)

    resumo = {
        "data_ini": data_ini,
        "data_fim": data_fim,
        "ano_meta": ano_meta,
        "mes_meta": mes_meta,
        "emissao": total_emissao,
        "pago": total_pago,
        "avencer": total_avencer,
        "quebra": total_quebra,
        "meta_geral": meta_geral,
        "faltante_geral": faltante_geral,
        "excedente_geral": excedente_geral,
        "pct_meta_geral": pct_meta_geral,
        "pct_meta_geral_css": format(limitar_percentual_css(pct_meta_geral), "f"),
        "classe_meta_geral": classe_percentual_meta(pct_meta_geral),
        "pct_pago": pct_pago,
        "pct_pago_css": format(limitar_percentual_css(pct_pago), "f"),
        "pct_avencer": pct_avencer,
        "pct_avencer_css": format(limitar_percentual_css(pct_avencer), "f"),
        "pct_quebra": pct_quebra,
        "pct_quebra_css": format(limitar_percentual_css(pct_quebra), "f"),
        "total_status": total_status,
        "qtd_registros": qs.count(),
        "qtd_metas": metas_qs.count(),
        "dias_uteis_mes": dias_uteis_mes,
        "dias_faltantes": dias_faltantes,
    }

    return {
        "resumo": resumo,
        "supervisores": supervisores_lista,
        "operadores": operadores_lista,
        "operador_carteira": operador_carteira_lista,
        "metas": list(metas_qs),
        "queryset": qs,
        "fora_do_padrao": fora_do_padrao,
    }
