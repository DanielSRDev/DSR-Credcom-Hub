from django.contrib import admin

from .models import (
    PlanilhaAcionamento,
    PlanilhaAcrescimo,
    PlanilhaCompartilhamento,
    PlanilhaContrato,
    PlanilhaImportacao,
    PlanilhaImportLog,
    PlanilhaStatusAcionamento,
)


@admin.register(PlanilhaCompartilhamento)
class PlanilhaCompartilhamentoAdmin(admin.ModelAdmin):
    list_display = ("usuario", "listar_colegas", "ativo", "criado_em")
    list_filter = ("ativo",)
    search_fields = ("usuario__username", "usuario__first_name", "usuario__last_name")
    filter_horizontal = ("colegas",)
    readonly_fields = ("criado_em",)

    @admin.display(description="Também vê a base de")
    def listar_colegas(self, obj):
        return ", ".join(str(c) for c in obj.colegas.all()) or "—"


@admin.register(PlanilhaStatusAcionamento)
class PlanilhaStatusAcionamentoAdmin(admin.ModelAdmin):
    list_display = ("nome", "ordem", "ativo")
    list_editable = ("ordem", "ativo")
    search_fields = ("nome",)


@admin.register(PlanilhaAcionamento)
class PlanilhaAcionamentoAdmin(admin.ModelAdmin):
    list_display = ("contrato", "status", "criado_por", "criado_em")
    list_filter = ("status",)
    search_fields = ("contrato__nr_contrato", "contrato__nome_cliente", "comentario")
    readonly_fields = ("criado_por", "criado_em")


@admin.register(PlanilhaImportacao)
class PlanilhaImportacaoAdmin(admin.ModelAdmin):
    list_display = ("carteira_nome", "cre_id", "total_contratos", "importado_por", "atualizado_em")
    search_fields = ("carteira_nome", "cre_id")
    readonly_fields = ("criado_em", "atualizado_em")


@admin.register(PlanilhaImportLog)
class PlanilhaImportLogAdmin(admin.ModelAdmin):
    list_display = (
        "carteira_nome", "cre_id", "importado_por", "total_inseridos",
        "total_removidos", "inconsistencias", "importado_mesmo_com_erros", "criado_em",
    )
    list_filter = ("importado_mesmo_com_erros",)
    search_fields = ("carteira_nome", "cre_id")
    readonly_fields = ("criado_em",)


class PlanilhaAcrescimoInline(admin.TabularInline):
    model = PlanilhaAcrescimo
    extra = 0
    readonly_fields = ("criado_por", "criado_em")


@admin.register(PlanilhaContrato)
class PlanilhaContratoAdmin(admin.ModelAdmin):
    list_display = (
        "nr_contrato", "nome_cliente", "operador_nome", "carteira_nome",
        "atraso_real", "vlr_total", "status_antigo", "prioridade", "destaque_cor",
    )
    list_filter = ("carteira_nome", "operador_nome", "prioridade", "status_antigo")
    search_fields = ("nr_contrato", "nome_cliente", "cpf_cnpj", "empreendimento")
    readonly_fields = ("criado_em", "prioridade_por", "prioridade_em")
    inlines = [PlanilhaAcrescimoInline]
