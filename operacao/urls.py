# operacao/urls.py
from django.urls import path
from . import views

app_name = "operacao"

urlpatterns = [
    path("", views.quadro, name="quadro"),

    path("criar/", views.tarefa_criar, name="criar"),
    path("editar/<int:tarefa_id>/", views.tarefa_editar, name="editar"),
    path("deletar/<int:tarefa_id>/", views.tarefa_deletar, name="deletar"),

    path("detalhe/<int:tarefa_id>/", views.detalhe, name="detalhe"),

    # comentários/anexos
    path("comentario/<int:tarefa_id>/", views.comentario_criar, name="comentario_criar"),
    path("anexos/<int:tarefa_id>/", views.anexos, name="anexos"),
    path("anexo/upload/<int:tarefa_id>/", views.anexo_upload, name="anexo_upload"),
    path("anexo/<int:anexo_id>/", views.anexo_download, name="anexo_download"),

    # status
    path("executando/<int:tarefa_id>/", views.marcar_executando, name="executando"),
    path("executado/<int:tarefa_id>/", views.marcar_executado, name="executado"),
    path("toggle/<int:tarefa_id>/", views.finalizar_reabrir, name="toggle"),

    # prioridade/ordem
    path("prioridade/<int:tarefa_id>/", views.toggle_prioridade, name="prioridade"),
    path("reordenar/", views.reordenar, name="reordenar"),
]