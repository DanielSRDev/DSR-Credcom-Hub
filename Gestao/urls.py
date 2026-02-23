# Gestao/urls.py
from django.urls import path
from . import views

app_name = "gestao"

urlpatterns = [
    path("", views.quadro, name="quadro"),
    path("criar/", views.tarefa_criar, name="criar"),
    path("editar/<int:pk>/", views.tarefa_editar, name="editar"),
    path("deletar/<int:pk>/", views.tarefa_deletar, name="deletar"),

    # detalhe
    path("detalhe/<int:pk>/", views.tarefa_detalhe, name="detalhe"),

    # status
    path("executando/<int:pk>/", views.tarefa_toggle_executando, name="executando"),
    path("executado/<int:pk>/", views.tarefa_marcar_executado, name="executado"),
    path("toggle/<int:pk>/", views.tarefa_toggle_status, name="toggle"),  # finalizar/reabrir (criador)

    # outros
    path("reordenar/", views.tarefa_reordenar, name="reordenar"),
    path("prioridade/<int:pk>/", views.tarefa_toggle_prioridade, name="prioridade"),

    # anexos
    path("anexos/<int:pk>/", views.tarefa_anexos, name="anexos"),
    path("anexos/<int:pk>/upload/", views.anexo_upload, name="anexo_upload"),
    path("anexo/<int:anexo_id>/download/", views.anexo_download, name="anexo_download"),

    # comentários
    path("comentario/<int:pk>/criar/", views.comentario_criar, name="comentario_criar"),
]