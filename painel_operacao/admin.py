from django.contrib import admin
from .models import (
    SupervisorPainel,
    CarteiraSupervisor,
    MetaOperadorCarteira,
    OperadorAlias,
    PainelConfiguracao,
    PainelSyncLog,
    PainelOperacaoPagamento,
    PainelOperacaoRegistro,
    PainelOperacaoRelatorioGeral,
)


@admin.register(SupervisorPainel)
class SupervisorPainelAdmin(admin.ModelAdmin):
    list_display = ("nome", "meta_diaria", "ativo", "ordem", "created_at")
    list_filter = ("ativo",)
    search_fields = ("nome",)
    ordering = ("ordem", "nome")


@admin.register(CarteiraSupervisor)
class CarteiraSupervisorAdmin(admin.ModelAdmin):
    list_display = ("credor_nome", "cre_id", "supervisor", "ativo")
    list_filter = ("ativo", "supervisor")
    search_fields = ("credor_nome", "cre_id", "supervisor__nome")
    ordering = ("credor_nome",)


@admin.register(MetaOperadorCarteira)
class MetaOperadorCarteiraAdmin(admin.ModelAdmin):
    list_display = (
        "ano",
        "mes",
        "carteira",
        "operador_nome",
        "operador_login",
        "meta_mensal",
        "ativo",
        "updated_at",
    )
    list_filter = (
        "ano",
        "mes",
        "ativo",
        "carteira__supervisor",
        "carteira",
    )
    search_fields = (
        "operador_nome",
        "operador_login",
        "carteira__credor_nome",
        "carteira__cre_id",
        "carteira__supervisor__nome",
    )
    autocomplete_fields = ("carteira",)
    ordering = ("-ano", "-mes", "carteira__credor_nome", "operador_nome")
    list_editable = ("meta_mensal", "ativo")


@admin.register(OperadorAlias)
class OperadorAliasAdmin(admin.ModelAdmin):
    list_display = ("login_original", "nome_exibicao", "ativo")
    list_filter = ("ativo",)
    search_fields = ("login_original", "nome_exibicao")
    ordering = ("nome_exibicao",)


@admin.register(PainelConfiguracao)
class PainelConfiguracaoAdmin(admin.ModelAdmin):
    list_display = (
        "meta_mensal_geral",
        "meta_diaria_geral",
        "intervalo_horas_sync",
        "ativo",
        "ultima_atualizacao",
    )


@admin.register(PainelSyncLog)
class PainelSyncLogAdmin(admin.ModelAdmin):
    list_display = ("tipo_sync", "iniciado_em", "finalizado_em", "sucesso", "total_registros")
    list_filter = ("tipo_sync", "sucesso")
    search_fields = ("mensagem",)
    readonly_fields = ("tipo_sync", "iniciado_em", "finalizado_em", "sucesso", "total_registros", "mensagem")


@admin.register(PainelOperacaoPagamento)
class PainelOperacaoPagamentoAdmin(admin.ModelAdmin):
    list_display = ("pgo_id", "aco_id", "pgo_data", "pgo_valor", "pct_id", "fpg_id")
    list_filter = ("fpg_id", "pgo_parcial")
    search_fields = ("pgo_id", "aco_id", "pct_id")
    readonly_fields = [field.name for field in PainelOperacaoPagamento._meta.fields]
    ordering = ("-pgo_data",)


@admin.register(PainelOperacaoRegistro)
class PainelOperacaoRegistroAdmin(admin.ModelAdmin):
    list_display = (
        "numero_acordo",
        "cliente",
        "credor",
        "emitido_por_nome",
        "supervisor_nome",
        "tem_pagamento",
        "valor_emissao",
        "valor_pago",
        "valor_avencer",
        "valor_quebra",
        "data_emissao",
    )
    list_filter = ("credor", "supervisor_nome", "emitido_por_nome", "status_acordo", "tem_pagamento")
    search_fields = ("numero_acordo", "cliente", "cpf_cnpj", "contrato", "emitido_por_login", "emitido_por_nome", "aco_id")
    readonly_fields = [field.name for field in PainelOperacaoRegistro._meta.fields]
    ordering = ("-data_emissao",)


@admin.register(PainelOperacaoRelatorioGeral)
class PainelOperacaoRelatorioGeralAdmin(admin.ModelAdmin):
    list_display = (
        "origem_registro",
        "numero_acordo",
        "cliente",
        "credor",
        "emitido_por_nome",
        "valor_emissao",
        "valor_pago",
        "valor_avencer",
        "valor_quebra",
        "data_pagamento",
        "data_emissao",
    )
    list_filter = ("origem_registro", "credor", "supervisor_nome", "emitido_por_nome", "status_acordo")
    search_fields = ("numero_acordo", "cliente", "cpf_cnpj", "contrato", "aco_id", "emitido_por_nome")
    readonly_fields = [field.name for field in PainelOperacaoRelatorioGeral._meta.fields]
    ordering = ("-data_referencia", "-data_pagamento", "-data_emissao")