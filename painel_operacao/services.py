from datetime import date, timedelta
from decimal import Decimal

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


def normalizar_bigint(valor):
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


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


def classificar_por_vencimento(data_acordo, tem_pagamento, honorario_liquido):
    """
    data_acordo = vencimento

    Regras:
    - tem pagamento -> Pago
    - sem pagamento e data_acordo < hoje -> Quebra
    - sem pagamento e data_acordo >= hoje -> A vencer
    """
    valor_emissao = honorario_liquido
    valor_pago = Decimal("0.00")
    valor_avencer = Decimal("0.00")
    valor_quebra = Decimal("0.00")

    hoje = timezone.localdate()

    if tem_pagamento:
        valor_pago = honorario_liquido
    else:
        if data_acordo and data_acordo.date() < hoje:
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
        tem_pagamento = aco_id in aco_ids_pagos if aco_id is not None else False

        valor_emissao, valor_pago, valor_avencer, valor_quebra = classificar_por_vencimento(
            data_acordo=data_acordo,
            tem_pagamento=tem_pagamento,
            honorario_liquido=honorario_liquido,
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


def pegar_mais_recente(lista_registros):
    if not lista_registros:
        return None
    return sorted(
        lista_registros,
        key=lambda r: data_comparacao_relatorio(r),
        reverse=True
    )[0]


def consolidar_registros_relatorio_geral(registros):
    """
    Regras por contrato:
    - QUEBRA + QUEBRA -> fica só a última QUEBRA
    - AVENCER + QUEBRA -> fica só AVENCER
    - PAGO + QUEBRA
      - se QUEBRA for mais recente -> ficam PAGO + QUEBRA
      - se PAGO for mais recente -> fica só PAGO
    - PAGO + AVENCER -> mantém os dois
    - só PAGO -> fica só o último
    - só AVENCER -> fica só o último
    """
    grupos = {}

    for registro in registros:
        chave = chave_contrato_relatorio(registro)
        grupos.setdefault(chave, []).append(registro)

    resultado_final = []

    for _, itens in grupos.items():
        pagos = []
        avencers = []
        quebras = []

        for item in itens:
            status = identificar_status_relatorio(item)
            if status == "PAGO":
                pagos.append(item)
            elif status == "AVENCER":
                avencers.append(item)
            else:
                quebras.append(item)

        pago_recente = pegar_mais_recente(pagos)
        avencer_recente = pegar_mais_recente(avencers)
        quebra_recente = pegar_mais_recente(quebras)

        if pago_recente and quebra_recente:
            data_pago = data_comparacao_relatorio(pago_recente)
            data_quebra = data_comparacao_relatorio(quebra_recente)

            if data_quebra > data_pago:
                resultado_final.append(pago_recente)
                resultado_final.append(quebra_recente)
            else:
                resultado_final.append(pago_recente)
            continue

        if avencer_recente and quebra_recente:
            resultado_final.append(avencer_recente)
            continue

        if pago_recente and avencer_recente:
            resultado_final.append(pago_recente)
            resultado_final.append(avencer_recente)
            continue

        if pago_recente:
            resultado_final.append(pago_recente)
            continue

        if avencer_recente:
            resultado_final.append(avencer_recente)
            continue

        if quebra_recente:
            resultado_final.append(quebra_recente)
            continue

    return resultado_final


def criar_registros_relatorio_geral(registros_hub, registros_pagos_extra):
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

        origem = (item.get("origem_registro") or "").strip().upper()
        valor_pago_periodo = decimal_or_zero(item.get("valor_pago_periodo"))

        tem_pagamento = valor_pago_periodo > 0 or origem == "PAGAMENTO_EXTRA"

        valor_emissao, valor_pago, valor_avencer, valor_quebra = classificar_por_vencimento(
            data_acordo=data_acordo,
            tem_pagamento=tem_pagamento,
            honorario_liquido=honorario_liquido,
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

    registros_consolidados = consolidar_registros_relatorio_geral(registros)
    return registros_consolidados


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
        registros_acordo_raw = executar_query(SQL_PAINEL_OPERACAO, [data_ini, data_fim])
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
        registros_hub = executar_query(SQL_RELATORIO_GERAL_HUB_BASE, [data_ini, data_fim])

        registros_pagos_extra = executar_query(
            SQL_RELATORIO_GERAL_PAGOS_EXTRA,
            [data_ini, data_fim, data_ini, data_fim]
        )

        registros = criar_registros_relatorio_geral(registros_hub, registros_pagos_extra)

        with transaction.atomic():
            PainelOperacaoRelatorioGeral.objects.all().delete()

            if registros:
                PainelOperacaoRelatorioGeral.objects.bulk_create(registros, batch_size=1000)

        mensagem = (
            f"Relatório geral sincronizado. "
            f"Base Hub: {len(registros_hub)} | Pagos Extra: {len(registros_pagos_extra)} | "
            f"Total salvo após consolidação: {len(registros)}"
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
            "total_hub": len(registros_hub),
            "total_pagos_extra": len(registros_pagos_extra),
        }

    except Exception as e:
        log.sucesso = False
        log.mensagem = str(e)
        log.finalizado_em = timezone.now()
        log.save()
        raise