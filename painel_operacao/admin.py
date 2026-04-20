from django.contrib import admin
from .models import (
    SupervisorPainel,
    CarteiraSupervisor,
    OperadorAlias,
    PainelConfiguracao,
    PainelSyncLog,
    PainelOperacaoRegistro,
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
    list_display = ("iniciado_em", "finalizado_em", "sucesso", "total_registros")
    list_filter = ("sucesso",)
    search_fields = ("mensagem",)
    readonly_fields = ("iniciado_em", "finalizado_em", "sucesso", "total_registros", "mensagem")


@admin.register(PainelOperacaoRegistro)
class PainelOperacaoRegistroAdmin(admin.ModelAdmin):
    list_display = (
        "numero_acordo",
        "cliente",
        "credor",
        "emitido_por_nome",
        "supervisor_nome",
        "valor_emissao",
        "valor_pago",
        "valor_avencer",
        "valor_quebra",
        "data_emissao",
    )
    list_filter = ("credor", "supervisor_nome", "emitido_por_nome", "status_acordo")
    search_fields = ("numero_acordo", "cliente", "cpf_cnpj", "contrato", "emitido_por_login", "emitido_por_nome")
    readonly_fields = [field.name for field in PainelOperacaoRegistro._meta.fields]
    ordering = ("-data_emissao",)