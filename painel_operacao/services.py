from datetime import date, timedelta
from decimal import Decimal

from django.db import connections, transaction
from django.utils import timezone

from .models import (
    OperadorAlias,
    CarteiraSupervisor,
    PainelConfiguracao,
    PainelOperacaoRegistro,
    PainelSyncLog,
)
from .queries import SQL_PAINEL_OPERACAO


def decimal_or_zero(value):
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value))


def normalizar_cre_id(valor):
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
        cre_id_normalizado = normalizar_cre_id(item.cre_id)
        if cre_id_normalizado is not None:
            mapa[cre_id_normalizado] = item.supervisor.nome

    return mapa


def executar_query_stage(data_ini, data_fim):
    with connections["cliente_db"].cursor() as cursor:
        cursor.execute(SQL_PAINEL_OPERACAO, [data_ini, data_fim])
        colunas = [col[0] for col in cursor.description]
        resultados = cursor.fetchall()

    registros = []
    for linha in resultados:
        registros.append(dict(zip(colunas, linha)))

    return registros


def classificar_status(status_acordo, honorario_liquido):
    status = (status_acordo or "").strip().lower()

    valor_emissao = honorario_liquido
    valor_pago = Decimal("0.00")
    valor_avencer = Decimal("0.00")
    valor_quebra = Decimal("0.00")

    if "pago" in status:
        valor_pago = honorario_liquido
    elif "aberto" in status:
        valor_avencer = honorario_liquido
    elif "quebr" in status:
        valor_quebra = honorario_liquido

    return valor_emissao, valor_pago, valor_avencer, valor_quebra


def tratar_registros(registros):
    aliases = buscar_alias_operadores()
    supervisores = buscar_mapa_supervisores()
    tratados = []

    for r in registros:
        login_original = (r.get("emitido_por") or "").strip()
        login_key = login_original.lower()
        nome_operador = aliases.get(login_key, login_original)

        cre_id = normalizar_cre_id(r.get("cre_id"))
        supervisor_nome = supervisores.get(cre_id, "SEM SUPERVISOR")

        honorario_liquido = decimal_or_zero(r.get("honorario_liquido"))
        status_acordo = r.get("status_acordo") or ""

        valor_emissao, valor_pago, valor_avencer, valor_quebra = classificar_status(
            status_acordo=status_acordo,
            honorario_liquido=honorario_liquido,
        )

        data_acordo = make_aware_if_needed(r.get("data_acordo"))
        data_emissao = make_aware_if_needed(r.get("data_emissao"))
        data_etl_alteracao = make_aware_if_needed(r.get("data_etl_alteracao"))
        data_referencia = data_emissao.date() if data_emissao else None

        registro = PainelOperacaoRegistro(
            data_referencia=data_referencia,
            data_acordo=data_acordo,
            data_emissao=data_emissao,
            data_etl_alteracao=data_etl_alteracao,

            numero_acordo=r.get("numero_acordo") or "",
            aco_id=r.get("aco_id"),
            contrato=r.get("contrato") or "",

            cliente=r.get("cliente") or "",
            cpf_cnpj=r.get("cpf_cnpj") or "",

            cre_id=cre_id,
            credor=r.get("credor") or "",
            filial=r.get("filial") or "",
            tipo_contrato=r.get("tipo_contrato") or "",
            tipo_negociacao=(r.get("tipo_negociacao") or "").strip(),

            principal_bruto=decimal_or_zero(r.get("principal_bruto")),
            desconto_principal=decimal_or_zero(r.get("desconto_principal")),
            principal_liquido=decimal_or_zero(r.get("principal_liquido")),

            multa_bruta=decimal_or_zero(r.get("multa_bruta")),
            desconto_multa=decimal_or_zero(r.get("desconto_multa")),
            multa_liquida=decimal_or_zero(r.get("multa_liquida")),

            juros_bruto=decimal_or_zero(r.get("juros_bruto")),
            desconto_juros=decimal_or_zero(r.get("desconto_juros")),
            juros_liquido=decimal_or_zero(r.get("juros_liquido")),

            honorario_bruto=decimal_or_zero(r.get("honorario_bruto")),
            desconto_honorario=decimal_or_zero(r.get("desconto_honorario")),
            honorario_liquido=honorario_liquido,

            despesas=decimal_or_zero(r.get("despesas")),
            subtotal_bruto=decimal_or_zero(r.get("subtotal_bruto")),
            desconto_total=decimal_or_zero(r.get("desconto_total")),
            valor_total_liquido=decimal_or_zero(r.get("valor_total_liquido")),
            valor_entrada=decimal_or_zero(r.get("valor_entrada")),

            qtd_parcelas_acordo=r.get("qtd_parcelas_acordo") or 0,
            status_acordo=status_acordo,
            tipo_acordo=r.get("tipo_acordo") or "",

            emitido_por_login=login_original,
            emitido_por_nome=nome_operador,
            supervisor_nome=supervisor_nome,

            valor_emissao=valor_emissao,
            valor_pago=valor_pago,
            valor_avencer=valor_avencer,
            valor_quebra=valor_quebra,
        )

        tratados.append(registro)

    return tratados


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
    )

    try:
        dados_stage = executar_query_stage(data_ini, data_fim)
        registros_tratados = tratar_registros(dados_stage)

        with transaction.atomic():
            PainelOperacaoRegistro.objects.all().delete()

            if registros_tratados:
                PainelOperacaoRegistro.objects.bulk_create(
                    registros_tratados,
                    batch_size=1000,
                )

        atualizar_configuracao()

        mensagem = f"Sincronização concluída. Total: {len(registros_tratados)}"

        log.sucesso = True
        log.total_registros = len(registros_tratados)
        log.mensagem = mensagem
        log.finalizado_em = timezone.now()
        log.save()

        return {
            "sucesso": True,
            "mensagem": mensagem,
            "total_registros": len(registros_tratados),
        }

    except Exception as e:
        log.sucesso = False
        log.mensagem = str(e)
        log.finalizado_em = timezone.now()
        log.save()
        raise