from django.contrib import admin
from .models import Equipe, Tarefa, Comentario, Anexo


@admin.register(Equipe)
class EquipeAdmin(admin.ModelAdmin):
    list_display = ("nome", "supervisor", "ativa")
    list_filter = ("ativa",)
    filter_horizontal = ("membros",)
    search_fields = ("nome", "supervisor__username", "membros__username")


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
        # Admin enxerga tudo
        return Tarefa.all_objects.all()

    def delete_model(self, request, obj):
        # delete no admin vira lixeira
        obj.soft_delete(request.user)

    def delete_queryset(self, request, queryset):
        # "delete selected" vira lixeira
        for obj in queryset:
            obj.soft_delete(request.user)


admin.site.register(Comentario)
admin.site.register(Anexo)