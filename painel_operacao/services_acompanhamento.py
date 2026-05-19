from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum

from .models import CarteiraSupervisor, MetaOperadorCarteira, PainelOperacaoRelatorioGeral, SupervisorPainel


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
    """
    Retorna todos os registros de PainelOperacaoRelatorioGeral sem filtros
    de credor ou operador.

    Motivo da mudança:
    - O filtro anterior cre_id__in=linked_credores_ids() descartava
      silenciosamente registros de credores ainda não cadastrados em
      CarteiraSupervisor, causando divergência entre o dashboard e o Excel.
    - O exclude(emitido_por_nome="") descartava registros onde o operador
      não foi resolvido via alias — esses aparecem normalmente no Excel.

    Filtros de credor/supervisor são aplicados em aplicar_filtros_relatorio
    apenas quando o usuário seleciona explicitamente. O dashboard sem filtro
    deve mostrar o mesmo total que o Excel exportado.
    """
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


def preparar_metricas_com_meta(item, meta):
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
    return item


def montar_acompanhamento_geral(data_ini=None, data_fim=None, supervisor=None, operador=None, credor=None):
    hoje = date.today()
    if data_fim is None:
        data_fim = hoje
    if data_ini is None:
        data_ini = date(data_fim.year, data_fim.month, 1)

    ano_meta = data_fim.year
    mes_meta = data_fim.month

    qs = aplicar_filtros_relatorio(
        data_ini=data_ini,
        data_fim=data_fim,
        supervisor=supervisor,
        operador=operador,
        credor=credor,
    ).order_by("emitido_por_nome", "credor", "-data_referencia")

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

        # Registros sem operador entram nos totais gerais mas não são
        # agrupados por operador/carteira (não existem na lista de metas).
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
        operadores_lista.append(preparar_metricas_com_meta(item, meta))

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
        supervisores_lista.append(preparar_metricas_com_meta(item, mapas_meta["supervisor"].get(nome, ZERO)))

    operador_carteira_lista = []
    for item in operador_carteira.values():
        chave_nome = normalizar_texto(item["operador"])
        chave_login = normalizar_texto(item["login"])
        cre_id = item["cre_id"]
        meta = mapas_meta["operador_carteira"].get((chave_nome, cre_id), ZERO)
        if not meta and chave_login:
            meta = mapas_meta["operador_carteira"].get((chave_login, cre_id), ZERO)
        operador_carteira_lista.append(preparar_metricas_com_meta(item, meta))

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
        operador_carteira_lista.append(preparar_metricas_com_meta(item, meta.meta_mensal))

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
    }

    return {
        "resumo": resumo,
        "supervisores": supervisores_lista,
        "operadores": operadores_lista,
        "operador_carteira": operador_carteira_lista,
        "metas": list(metas_qs),
        "queryset": qs,
    }