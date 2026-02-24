from django.contrib import admin
from .models import Equipe, Tarefa, Comentario, Anexo


@admin.register(Equipe)
class EquipeAdmin(admin.ModelAdmin):
    list_display = ("nome", "supervisor", "ativa")
    list_filter = ("ativa",)
    filter_horizontal = ("membros",)
    search_fields = ("nome", "supervisor__username", "membros__username")


@admin.register(Tarefa)
class TarefaAdmin(admin.ModelAdmin):
    list_display = ("id", "titulo", "status", "atribuida_para", "criada_por", "prazo", "prioridade")
    list_filter = ("status", "prioridade")
    search_fields = ("titulo", "descricao", "atribuida_para__username", "criada_por__username")


admin.site.register(Comentario)
admin.site.register(Anexo)