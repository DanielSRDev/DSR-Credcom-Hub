from django.contrib import admin
from .models import Equipe, Tarefa, Comentario, Anexo, OperacaoPermissaoUsuario


@admin.register(Equipe)
class EquipeAdmin(admin.ModelAdmin):
    list_display = ("nome", "lista_supervisores", "ativa")
    list_filter = ("ativa",)
    # supervisores entra no filter_horizontal junto com membros —
    # o widget de dupla coluna é o mais ergonômico para M2M no admin.
    filter_horizontal = ("supervisores", "membros",)
    search_fields = ("nome", "supervisores__username", "membros__username")

    @admin.display(description="Supervisores")
    def lista_supervisores(self, obj):
        """
        Substitui o campo supervisor direto (que era FK e podia ser
        exibido diretamente no list_display) por um método que monta
        a lista de usernames do ManyToMany.
        Usado apenas na listagem — não interfere no formulário.
        """
        return ", ".join(
            obj.supervisores.values_list("username", flat=True)
        ) or "-"


@admin.action(description="Restaurar tarefas selecionadas (tirar da lixeira)")
def restore_tarefas(modeladmin, request, queryset):
    queryset.update(deleted_at=None, deleted_by=None)


@admin.action(description="Deletar de vez (PERMANENTE)")
def hard_delete_tarefas(modeladmin, request, queryset):
    queryset.delete()


@admin.register(Tarefa)
class TarefaAdmin(admin.ModelAdmin):
    list_display = ("id", "titulo", "status", "prazo", "prioridade", "deleted_at")
    list_filter = ("status", "prioridade", "deleted_at")
    search_fields = ("titulo", "descricao")
    actions = [restore_tarefas, hard_delete_tarefas]

    def get_queryset(self, request):
        return Tarefa.all_objects.all()

    def delete_model(self, request, obj):
        obj.soft_delete(request.user)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            obj.soft_delete(request.user)


@admin.register(OperacaoPermissaoUsuario)
class OperacaoPermissaoUsuarioAdmin(admin.ModelAdmin):
    list_display = ("user", "bloquear_criar_chamado_supervisor")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    list_filter = ("bloquear_criar_chamado_supervisor",)


admin.site.register(Comentario)
admin.site.register(Anexo)