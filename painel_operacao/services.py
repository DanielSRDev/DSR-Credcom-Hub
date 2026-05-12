from datetime import date, timedelta
import calendar
from decimal import Decimal
import re
import unicodedata

from django.db import connections, transaction
from django.utils import timezone

from .models import (
    OperadorAlias,
    CarteiraSupervisor,
    PainelConfiguracao,
    PainelOperacaoPagamento,
    PainelOperacaoRegistro,
    PainelOperacaoRelatorioGeral,
    PainelSyncLog,
)
from .queries import (
    SQL_PAGAMENTOS_ACORDO,
    SQL_PAINEL_OPERACAO,
    SQL_RELATORIO_GERAL_HUB_BASE,
    SQL_RELATORIO_GERAL_PAGOS_EXTRA,
)


def decimal_or_zero(value):
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value))


def calcular_valores_acordo_planilha(principal_liquido, multa_liquida, juros_liquido, honorario_liquido):
    """
    Valores adicionais usados somente na Planilha Geral.

    Valor Parcela = principal líquido + multa líquida + juros líquido.
    Vlr. Total Acordo = Valor Parcela + honorário líquido.

    Esses campos não alteram a regra do HUB:
    Emissão/Pago/A vencer/Quebra continuam usando honorário líquido.
    """
    principal_liquido = decimal_or_zero(principal_liquido)
    multa_liquida = decimal_or_zero(multa_liquida)
    juros_liquido = decimal_or_zero(juros_liquido)
    honorario_liquido = decimal_or_zero(honorario_liquido)

    valor_parcela = principal_liquido + multa_liquida + juros_liquido
    valor_total_acordo = valor_parcela + honorario_liquido

    return valor_parcela, valor_total_acordo


def normalizar_bigint(valor):
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None

def normalizar_status_texto(valor):
    """
    Normaliza o texto do status para comparação segura.
    Exemplo: "Pago", "PAGO", "pago " e variações com acento viram uma base comparável.
    """
    if valor is None:
        return ""

    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return texto


def eh_status_pago(valor):
    """
    Regra de negócio: status original contendo PAGO também prova pagamento.

    Isso cobre acordos que aparecem como pagos no Cobmais/stage, mas não possuem baixa
    em dbo.tb_pagamento, geralmente por PIX, baixa externa ou outro fluxo fora da tabela.
    """
    status = normalizar_status_texto(valor)

    if not status:
        return False

    # Evita falso positivo em textos como "NAO PAGO" ou "IMPAGO".
    if re.search(r"\bNAO\s+PAGO\b", status) or re.search(r"\bIMPAGO\b", status):
        return False

    return (
        re.search(r"\bPAGO\b", status) is not None
        or re.search(r"\bLIQUIDADO\b", status) is not None
        or re.search(r"\bBAIXADO\b", status) is not None
    )


def normalizar_data(value):
    if value is None:
        return None

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        return date.fromisoformat(value)

    if hasattr(value, "date"):
        return value.date()

    return value



def ultimo_dia_mes(data_ref):
    """
    Retorna o último dia do mês da data informada.

    Regra do HUB:
    - o período filtra DATA EMISSÃO;
    - acordos com DATA ACORDO no mês seguinte não entram;
    - se o filtro for 01/04 a 29/04, vencimento 30/04 ainda é do mesmo mês e deve entrar.
    """
    data_ref = normalizar_data(data_ref)
    ultimo_dia = calendar.monthrange(data_ref.year, data_ref.month)[1]
    return date(data_ref.year, data_ref.month, ultimo_dia)

def make_aware_if_needed(dt):
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def buscar_alias_operadores():
    mapa = {}
    for item in OperadorAlias.objects.filter(ativo=True):
        mapa[item.login_original.strip().lower()] = item.nome_exibicao.strip()
    return mapa


def buscar_mapa_supervisores():
    mapa = {}
    queryset = CarteiraSupervisor.objects.select_related("supervisor").filter(
        ativo=True,
        supervisor__ativo=True,
    )

    for item in queryset:
        cre_id_normalizado = normalizar_bigint(item.cre_id)
        if cre_id_normalizado is not None:
            mapa[cre_id_normalizado] = item.supervisor.nome

    return mapa


def executar_query(query, params, alias="cliente_db"):
    with connections[alias].cursor() as cursor:
        cursor.execute(query, params)
        colunas = [col[0] for col in cursor.description]
        resultados = cursor.fetchall()

    registros = []
    for linha in resultados:
        registros.append(dict(zip(colunas, linha)))
    return registros


def criar_pagamentos_locais(registros_pagamento):
    pagamentos = []

    for item in registros_pagamento:
        pagamentos.append(
            PainelOperacaoPagamento(
                pgo_id=normalizar_bigint(item.get("pgo_id")),
                aco_id=normalizar_bigint(item.get("aco_id")),
                pct_id=normalizar_bigint(item.get("pct_id")),
                pgo_data=make_aware_if_needed(item.get("pgo_data")),
                pgo_valor=decimal_or_zero(item.get("pgo_valor")),
                fpg_id=item.get("fpg_id"),
                pgo_parcial=bool(item.get("pgo_parcial")),
                pgo_etl_alteracao=make_aware_if_needed(item.get("pgo_etl_alteracao")),
            )
        )

    return pagamentos


def classificar_por_vencimento(data_acordo, tem_pagamento, honorario_liquido, data_base=None):
    """
    data_acordo = vencimento

    Regras:
    - tem pagamento -> Pago
    - sem pagamento e data_acordo < data_base -> Quebra
    - sem pagamento e data_acordo >= data_base -> A vencer

    data_base normalmente é hoje, seguindo a regra operacional do painel.
    """
    valor_emissao = honorario_liquido
    valor_pago = Decimal("0.00")
    valor_avencer = Decimal("0.00")
    valor_quebra = Decimal("0.00")

    if data_base is None:
        data_base = timezone.localdate()

    data_base = normalizar_data(data_base)

    if tem_pagamento:
        valor_pago = honorario_liquido
    else:
        if data_acordo and data_acordo.date() < data_base:
            valor_quebra = honorario_liquido
        else:
            valor_avencer = honorario_liquido

    return valor_emissao, valor_pago, valor_avencer, valor_quebra


def criar_registros_locais(registros_acordo, aco_ids_pagos):
    aliases = buscar_alias_operadores()
    supervisores = buscar_mapa_supervisores()
    registros = []

    for item in registros_acordo:
        login_original = (item.get("emitido_por") or "").strip()
        nome_operador = aliases.get(login_original.lower(), login_original)

        cre_id = normalizar_bigint(item.get("cre_id"))
        supervisor_nome = supervisores.get(cre_id, "SEM SUPERVISOR")

        aco_id = normalizar_bigint(item.get("aco_id"))
        data_acordo = make_aware_if_needed(item.get("data_acordo"))
        data_emissao = make_aware_if_needed(item.get("data_emissao"))
        data_etl_alteracao = make_aware_if_needed(item.get("data_etl_alteracao"))
        data_referencia = data_emissao.date() if data_emissao else None

        honorario_liquido = decimal_or_zero(item.get("honorario_liquido"))
        status_original = item.get("status_acordo") or ""
        tem_pagamento_real = aco_id in aco_ids_pagos if aco_id is not None else False
        tem_pagamento = tem_pagamento_real or eh_status_pago(status_original)

        valor_emissao, valor_pago, valor_avencer, valor_quebra = classificar_por_vencimento(
            data_acordo=data_acordo,
            tem_pagamento=tem_pagamento,
            honorario_liquido=honorario_liquido,
            data_base=timezone.localdate(),
        )

        registros.append(
            PainelOperacaoRegistro(
                data_referencia=data_referencia,
                data_acordo=data_acordo,
                data_emissao=data_emissao,
                data_etl_alteracao=data_etl_alteracao,

                numero_acordo=item.get("numero_acordo") or "",
                aco_id=aco_id,
                contrato=item.get("contrato") or "",
                con_id=normalizar_bigint(item.get("con_id")),
                observacao_contrato=item.get("observacao_contrato") or "",

                cliente=item.get("cliente") or "",
                cpf_cnpj=item.get("cpf_cnpj") or "",

                cre_id=cre_id,
                credor=item.get("credor") or "",
                filial=item.get("filial") or "",
                tipo_contrato=item.get("tipo_contrato") or "",
                tipo_negociacao=(item.get("tipo_negociacao") or "").strip(),

                principal_bruto=decimal_or_zero(item.get("principal_bruto")),
                desconto_principal=decimal_or_zero(item.get("desconto_principal")),
                principal_liquido=decimal_or_zero(item.get("principal_liquido")),

                multa_bruta=decimal_or_zero(item.get("multa_bruta")),
                desconto_multa=decimal_or_zero(item.get("desconto_multa")),
                multa_liquida=decimal_or_zero(item.get("multa_liquida")),

                juros_bruto=decimal_or_zero(item.get("juros_bruto")),
                desconto_juros=decimal_or_zero(item.get("desconto_juros")),
                juros_liquido=decimal_or_zero(item.get("juros_liquido")),

                honorario_bruto=decimal_or_zero(item.get("honorario_bruto")),
                desconto_honorario=decimal_or_zero(item.get("desconto_honorario")),
                honorario_liquido=honorario_liquido,

                despesas=decimal_or_zero(item.get("despesas")),
                despesa_liquida=decimal_or_zero(item.get("despesa_liquida")),
                subtotal_bruto=decimal_or_zero(item.get("subtotal_bruto")),
                desconto_total=decimal_or_zero(item.get("desconto_total")),
                valor_total_liquido=decimal_or_zero(item.get("valor_total_liquido")),
                valor_entrada=decimal_or_zero(item.get("valor_entrada")),

                qtd_parcelas_acordo=item.get("qtd_parcelas_acordo") or 0,
                status_acordo=item.get("status_acordo") or "",
                tipo_acordo=item.get("tipo_acordo") or "",

                emitido_por_login=login_original,
                emitido_por_nome=nome_operador,
                supervisor_nome=supervisor_nome,

                tem_pagamento=tem_pagamento,
                valor_emissao=valor_emissao,
                valor_pago=valor_pago,
                valor_avencer=valor_avencer,
                valor_quebra=valor_quebra,
            )
        )

    return registros



def classificar_item_painel_para_relatorio(item):
    """
    Mesma regra visual do HUB:
    - tem_pagamento=True => PAGO
    - sem pagamento e data_acordo < hoje => QUEBRA
    - sem pagamento e data_acordo >= hoje => AVENCER
    """
    hoje = timezone.localdate()

    if item.tem_pagamento or eh_status_pago(item.status_acordo):
        return "PAGO"

    if item.data_acordo and item.data_acordo.date() < hoje:
        return "QUEBRA"

    return "AVENCER"


def data_comparacao_painel_para_relatorio(item):
    return item.data_emissao or item.data_acordo or item.data_etl_alteracao or item.created_at


def chave_contrato_painel_para_relatorio(item):
    contrato = (item.contrato or "").strip()
    if contrato:
        return contrato

    if item.aco_id:
        return f"ACO_{item.aco_id}"

    numero_acordo = (item.numero_acordo or "").strip()
    if numero_acordo:
        return f"NUM_{numero_acordo}"

    return f"REG_{item.id}"


def pegar_mais_recente_painel_para_relatorio(itens):
    if not itens:
        return None

    return sorted(
        itens,
        key=lambda item: data_comparacao_painel_para_relatorio(item) or item.created_at,
        reverse=True,
    )[0]


def consolidar_itens_painel_para_relatorio(itens):
    """
    Copia a mesma consolidação usada no HUB para garantir que:
    AVENCER relatório = AVENCER HUB
    QUEBRA relatório = QUEBRA HUB

    Regra operacional atual:
    - Vários PAGO no mesmo contrato/período: mantém todos.
    - Vários A VENCER no mesmo contrato/período: mantém todos.
    - Várias QUEBRA no mesmo contrato/período: mantém somente a quebra mais recente.
    - PAGO mais recente que QUEBRA antiga: mantém somente os pagos.
    - QUEBRA mais recente que o último PAGO: mantém todos os pagos + a quebra mais recente.
    - A VENCER + QUEBRA, sem pago: mantém os A VENCER e ignora a quebra.
    - PAGO + A VENCER: mantém todos os pagos + todos os A VENCER e ignora quebra antiga.
    """
    grupos = {}

    for item in itens:
        chave = chave_contrato_painel_para_relatorio(item)
        grupos.setdefault(chave, []).append(item)

    resultado = []

    for grupo in grupos.values():
        pagos = []
        avencers = []
        quebras = []

        for item in grupo:
            status = classificar_item_painel_para_relatorio(item)

            if status == "PAGO":
                pagos.append(item)
            elif status == "AVENCER":
                avencers.append(item)
            else:
                quebras.append(item)

        pagos = sorted(
            pagos,
            key=lambda item: data_comparacao_painel_para_relatorio(item) or item.created_at,
            reverse=True,
        )
        avencers = sorted(
            avencers,
            key=lambda item: data_comparacao_painel_para_relatorio(item) or item.created_at,
            reverse=True,
        )
        quebras = sorted(
            quebras,
            key=lambda item: data_comparacao_painel_para_relatorio(item) or item.created_at,
            reverse=True,
        )

        quebra_recente = quebras[0] if quebras else None

        # Se existe acordo A VENCER, ele representa negociação ativa/futura.
        # Nesse cenário a quebra antiga do mesmo contrato não deve entrar no relatório HUB.
        if avencers:
            resultado.extend(pagos)
            resultado.extend(avencers)
            continue

        if pagos:
            resultado.extend(pagos)

            if quebra_recente:
                ultimo_pago = pagos[0]
                data_pago = data_comparacao_painel_para_relatorio(ultimo_pago) or ultimo_pago.created_at
                data_quebra = data_comparacao_painel_para_relatorio(quebra_recente) or quebra_recente.created_at

                # Quebra só entra junto se ela for posterior ao pagamento mais recente.
                if data_quebra > data_pago:
                    resultado.append(quebra_recente)

            continue

        if quebra_recente:
            resultado.append(quebra_recente)
            continue

    return resultado

def valores_item_painel_para_relatorio(item):
    valor = decimal_or_zero(item.honorario_liquido)
    status = classificar_item_painel_para_relatorio(item)

    valor_emissao = valor
    valor_pago = Decimal("0.00")
    valor_avencer = Decimal("0.00")
    valor_quebra = Decimal("0.00")

    if status == "PAGO":
        valor_pago = valor
    elif status == "AVENCER":
        valor_avencer = valor
    else:
        valor_quebra = valor

    return valor_emissao, valor_pago, valor_avencer, valor_quebra


def criar_registros_relatorio_a_partir_painel(itens_painel):
    """
    Cria a parte HUB do Relatório Geral usando exatamente os itens já consolidados do HUB.
    Isso elimina divergência entre painel e relatório para AVENCER/QUEBRA.
    """
    registros = []

    for item in itens_painel:
        valor_emissao, valor_pago, valor_avencer, valor_quebra = valores_item_painel_para_relatorio(item)

        principal_liquido = decimal_or_zero(item.principal_liquido)
        multa_liquida = decimal_or_zero(item.multa_liquida)
        juros_liquido = decimal_or_zero(item.juros_liquido)
        honorario_liquido = decimal_or_zero(item.honorario_liquido)
        valor_parcela, valor_total_acordo = calcular_valores_acordo_planilha(
            principal_liquido=principal_liquido,
            multa_liquida=multa_liquida,
            juros_liquido=juros_liquido,
            honorario_liquido=honorario_liquido,
        )

        registros.append(
            PainelOperacaoRelatorioGeral(
                origem_registro="HUB",
                data_referencia=item.data_referencia,
                data_acordo=item.data_acordo,
                data_emissao=item.data_emissao,
                data_pagamento=None,
                data_etl_alteracao=item.data_etl_alteracao,

                numero_acordo=item.numero_acordo or "",
                aco_id=item.aco_id,
                contrato=item.contrato or "",
                con_id=item.con_id,
                observacao_contrato=getattr(item, "observacao_contrato", "") or "",

                cliente=item.cliente or "",
                cpf_cnpj=item.cpf_cnpj or "",

                cre_id=item.cre_id,
                credor=item.credor or "",
                filial=item.filial or "",
                tipo_contrato=item.tipo_contrato or "",
                tipo_negociacao=(item.tipo_negociacao or "").strip(),

                honorario_bruto=decimal_or_zero(item.honorario_bruto),
                desconto_honorario=decimal_or_zero(item.desconto_honorario),
                honorario_liquido=honorario_liquido,

                principal_liquido=principal_liquido,
                multa_liquida=multa_liquida,
                juros_liquido=juros_liquido,
                valor_parcela=valor_parcela,
                valor_total_acordo=valor_total_acordo,
                despesa_liquida=decimal_or_zero(item.despesa_liquida),
                valor_pagamento_periodo=Decimal("0.00"),

                qtd_parcelas_acordo=item.qtd_parcelas_acordo or 0,
                status_acordo=item.status_acordo or "",
                tipo_acordo=item.tipo_acordo or "",

                emitido_por_login=item.emitido_por_login or "",
                emitido_por_nome=item.emitido_por_nome or "",
                supervisor_nome=item.supervisor_nome or "",

                valor_emissao=valor_emissao,
                valor_pago=valor_pago,
                valor_avencer=valor_avencer,
                valor_quebra=valor_quebra,
            )
        )

    return registros

def identificar_status_relatorio(registro):
    if decimal_or_zero(registro.valor_pago) > 0:
        return "PAGO"
    if decimal_or_zero(registro.valor_avencer) > 0:
        return "AVENCER"
    return "QUEBRA"


def data_comparacao_relatorio(registro):
    return (
        registro.data_pagamento
        or registro.data_emissao
        or registro.data_acordo
        or registro.data_etl_alteracao
        or timezone.now()
    )


def chave_contrato_relatorio(registro):
    contrato = (registro.contrato or "").strip()
    if contrato:
        return contrato

    if registro.aco_id:
        return f"ACO_{registro.aco_id}"

    numero_acordo = (registro.numero_acordo or "").strip()
    if numero_acordo:
        return f"NUM_{numero_acordo}"

    return f"REG_{id(registro)}"


def consolidar_registros_relatorio_geral(registros):
    """
    Consolidação do Relatório Geral.

    Regra acordada:
    - vários pagos no mês: mantém todos;
    - pago + a vencer: mantém ambos;
    - pago + quebra: mantém pago e a última quebra;
    - a vencer + quebra, sem pago: mantém só a vencer;
    - várias quebras: mantém só a última quebra.

    O valor financeiro do relatório nunca vem de pgo_valor.
    O pagamento só prova status PAGO. O valor salvo continua sendo honorário líquido.
    """
    grupos = {}

    for registro in registros:
        chave = chave_contrato_relatorio(registro)
        grupos.setdefault(chave, []).append(registro)

    resultado = []

    for itens in grupos.values():
        pagos = []
        avencer = []
        quebras = []

        for item in itens:
            status = identificar_status_relatorio(item)

            if status == "PAGO":
                pagos.append(item)
            elif status == "AVENCER":
                avencer.append(item)
            else:
                quebras.append(item)

        pagos = sorted(pagos, key=data_comparacao_relatorio, reverse=True)
        avencer = sorted(avencer, key=data_comparacao_relatorio, reverse=True)
        quebras = sorted(quebras, key=data_comparacao_relatorio, reverse=True)

        if pagos:
            resultado.extend(pagos)

            if avencer:
                resultado.extend(avencer)
            elif quebras:
                resultado.append(quebras[0])

            continue

        if avencer:
            resultado.extend(avencer)
            continue

        if quebras:
            resultado.append(quebras[0])

    return resultado


def criar_registros_relatorio_geral(registros_hub, registros_pagos_extra, data_base=None):
    aliases = buscar_alias_operadores()
    supervisores = buscar_mapa_supervisores()
    registros = []

    def processar(item):
        login_original = (item.get("emitido_por_login") or "").strip()
        nome_operador = aliases.get(login_original.lower(), login_original) if login_original else ""

        cre_id = normalizar_bigint(item.get("cre_id"))
        supervisor_nome = supervisores.get(cre_id, "SEM SUPERVISOR") if cre_id is not None else ""

        data_acordo = make_aware_if_needed(item.get("data_acordo"))
        data_emissao = make_aware_if_needed(item.get("data_emissao"))
        data_pagamento = make_aware_if_needed(item.get("data_pagamento"))
        data_etl_alteracao = make_aware_if_needed(item.get("data_etl_alteracao"))

        data_referencia = None
        if data_pagamento:
            data_referencia = data_pagamento.date()
        elif data_emissao:
            data_referencia = data_emissao.date()
        elif data_acordo:
            data_referencia = data_acordo.date()

        honorario_bruto = decimal_or_zero(item.get("honorario_bruto"))
        desconto_honorario = decimal_or_zero(item.get("desconto_honorario"))
        honorario_liquido = decimal_or_zero(item.get("honorario_liquido"))

        principal_liquido = decimal_or_zero(item.get("principal_liquido"))
        multa_liquida = decimal_or_zero(item.get("multa_liquida"))
        juros_liquido = decimal_or_zero(item.get("juros_liquido"))
        despesa_liquida = decimal_or_zero(item.get("despesa_liquida"))
        valor_pagamento_periodo = decimal_or_zero(item.get("valor_pago_periodo"))
        valor_parcela, valor_total_acordo = calcular_valores_acordo_planilha(
            principal_liquido=principal_liquido,
            multa_liquida=multa_liquida,
            juros_liquido=juros_liquido,
            honorario_liquido=honorario_liquido,
        )

        origem = (item.get("origem_registro") or "").strip().upper()
        status_original = item.get("status_acordo") or ""
        tem_pagamento_real = valor_pagamento_periodo > 0
        pago_sem_baixa_real = (not tem_pagamento_real) and eh_status_pago(status_original)
        tem_pagamento = tem_pagamento_real or pago_sem_baixa_real

        if pago_sem_baixa_real:
            origem = "PAGO_SEM_BAIXA_REAL"

        # REGRA FINAL:
        # - HUB classifica normal: PAGO / AVENCER / QUEBRA
        # - PAGAMENTO_EXTRA entra somente em EMISSÃO + PAGO
        # - PAGAMENTO_EXTRA nunca movimenta AVENCER/QUEBRA
        if origem == "PAGAMENTO_EXTRA":
            valor_emissao = honorario_liquido
            valor_pago = honorario_liquido
            valor_avencer = Decimal("0.00")
            valor_quebra = Decimal("0.00")
        else:
            valor_emissao, valor_pago, valor_avencer, valor_quebra = classificar_por_vencimento(
                data_acordo=data_acordo,
                tem_pagamento=tem_pagamento,
                honorario_liquido=honorario_liquido,
                data_base=timezone.localdate(),
            )

        registros.append(
            PainelOperacaoRelatorioGeral(
                origem_registro=origem,
                data_referencia=data_referencia,
                data_acordo=data_acordo,
                data_emissao=data_emissao,
                data_pagamento=data_pagamento,
                data_etl_alteracao=data_etl_alteracao,

                numero_acordo=item.get("numero_acordo") or "",
                aco_id=normalizar_bigint(item.get("aco_id")),
                contrato=item.get("contrato") or "",
                con_id=normalizar_bigint(item.get("con_id")),
                observacao_contrato=item.get("observacao_contrato") or "",

                cliente=item.get("cliente") or "",
                cpf_cnpj=item.get("cpf_cnpj") or "",

                cre_id=cre_id,
                credor=item.get("credor") or "",
                filial=item.get("filial") or "",
                tipo_contrato=item.get("tipo_contrato") or "",
                tipo_negociacao=(item.get("tipo_negociacao") or "").strip(),

                honorario_bruto=honorario_bruto,
                desconto_honorario=desconto_honorario,
                honorario_liquido=honorario_liquido,

                principal_liquido=principal_liquido,
                multa_liquida=multa_liquida,
                juros_liquido=juros_liquido,
                valor_parcela=valor_parcela,
                valor_total_acordo=valor_total_acordo,
                despesa_liquida=despesa_liquida,
                valor_pagamento_periodo=valor_pagamento_periodo,

                qtd_parcelas_acordo=item.get("qtd_parcelas_acordo") or 0,
                status_acordo=item.get("status_acordo") or "",
                tipo_acordo=item.get("tipo_acordo") or "",

                emitido_por_login=login_original,
                emitido_por_nome=nome_operador,
                supervisor_nome=supervisor_nome,

                valor_emissao=valor_emissao,
                valor_pago=valor_pago,
                valor_avencer=valor_avencer,
                valor_quebra=valor_quebra,
            )
        )

    for item in registros_hub:
        processar(item)

    for item in registros_pagos_extra:
        processar(item)

    # Não consolidar aqui. A base HUB já vem consolidada igual ao painel,
    # e pagamentos extras devem permanecer como linhas extras de PAGO.
    return registros


def atualizar_configuracao():
    config = PainelConfiguracao.objects.filter(ativo=True).first()
    if config:
        config.ultima_atualizacao = timezone.now()
        config.save(update_fields=["ultima_atualizacao", "updated_at"])


def sincronizar_painel_operacao(data_ini=None, data_fim=None):
    if data_fim is None:
        data_fim = date.today()
    if data_ini is None:
        data_ini = data_fim - timedelta(days=30)

    log = PainelSyncLog.objects.create(
        sucesso=False,
        total_registros=0,
        mensagem="Iniciando sincronização.",
        tipo_sync="PAINEL",
    )

    try:
        # Regra de competência do HUB:
        # 1) puxa pela Data Emissão dentro do período filtrado;
        # 2) NÃO corta vencimentos do mesmo mês quando o filtro termina antes do fim do mês;
        # 3) exclui apenas acordos cuja Data Acordo/Vencimento esteja no mês seguinte.
        # Ex.: filtro 01/04 a 29/04 inclui vencimento 30/04, mas exclui vencimento 05/05.
        data_limite_vencimento = ultimo_dia_mes(data_fim)
        registros_acordo_raw = executar_query(
            SQL_PAINEL_OPERACAO,
            [data_ini, data_fim, data_limite_vencimento],
        )
        registros_pagamento_raw = executar_query(SQL_PAGAMENTOS_ACORDO, [data_ini, data_fim])

        aco_ids_pagos = {
            normalizar_bigint(item.get("aco_id"))
            for item in registros_pagamento_raw
            if normalizar_bigint(item.get("aco_id")) is not None
        }

        pagamentos_locais = criar_pagamentos_locais(registros_pagamento_raw)
        registros_locais = criar_registros_locais(registros_acordo_raw, aco_ids_pagos)

        with transaction.atomic():
            PainelOperacaoPagamento.objects.all().delete()
            PainelOperacaoRegistro.objects.all().delete()

            if pagamentos_locais:
                PainelOperacaoPagamento.objects.bulk_create(pagamentos_locais, batch_size=1000)

            if registros_locais:
                PainelOperacaoRegistro.objects.bulk_create(registros_locais, batch_size=1000)

        atualizar_configuracao()

        mensagem = (
            f"Sincronização concluída. "
            f"Acordos: {len(registros_locais)} | Pagamentos: {len(pagamentos_locais)}"
        )

        log.sucesso = True
        log.total_registros = len(registros_locais)
        log.mensagem = mensagem
        log.finalizado_em = timezone.now()
        log.save()

        return {
            "sucesso": True,
            "mensagem": mensagem,
            "total_registros": len(registros_locais),
            "total_pagamentos": len(pagamentos_locais),
        }

    except Exception as e:
        log.sucesso = False
        log.mensagem = str(e)
        log.finalizado_em = timezone.now()
        log.save()
        raise



def sincronizar_relatorio_geral(data_ini=None, data_fim=None):
    if data_fim is None:
        data_fim = date.today()
    if data_ini is None:
        data_ini = data_fim - timedelta(days=30)

    log = PainelSyncLog.objects.create(
        sucesso=False,
        total_registros=0,
        mensagem="Iniciando sincronização do relatório geral.",
        tipo_sync="RELATORIO_GERAL",
    )

    try:
        base_hub = list(
            PainelOperacaoRegistro.objects.filter(
                data_referencia__gte=data_ini,
                data_referencia__lte=data_fim,
            )
        )

        base_hub_consolidada = consolidar_itens_painel_para_relatorio(base_hub)

        registros = criar_registros_relatorio_a_partir_painel(base_hub_consolidada)

        pagamentos_extra_raw = executar_query(SQL_RELATORIO_GERAL_PAGOS_EXTRA, [data_ini, data_fim])
        registros_pagos_extra = criar_registros_relatorio_geral([], pagamentos_extra_raw)
        registros.extend(registros_pagos_extra)

        with transaction.atomic():
            PainelOperacaoRelatorioGeral.objects.all().delete()
            if registros:
                PainelOperacaoRelatorioGeral.objects.bulk_create(registros, batch_size=1000)

        mensagem = (
            f"Relatório geral OK. "
            f"Hub consolidado: {len(base_hub_consolidada)} | "
            f"Pagamentos extras: {len(pagamentos_extra_raw)} | "
            f"Total salvo: {len(registros)}"
        )

        log.sucesso = True
        log.total_registros = len(registros)
        log.mensagem = mensagem
        log.finalizado_em = timezone.now()
        log.save()

        return {
            "sucesso": True,
            "mensagem": mensagem,
            "total_registros": len(registros),
        }

    except Exception as e:
        log.sucesso = False
        log.mensagem = str(e)
        log.finalizado_em = timezone.now()
        log.save()
        raise