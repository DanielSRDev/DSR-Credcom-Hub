from django.urls import path
from . import views

app_name = "zapmsg"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("iniciar/", views.iniciar_conexao, name="iniciar"),
    path("status/", views.status_conexao, name="status"),
    path("desconectar/", views.desconectar, name="desconectar"),
    path("api/targets/", views.api_targets, name="api_targets"),
    path("api/conversas/", views.api_conversas, name="api_conversas"),
    path("api/conversas/<int:conversa_id>/mensagens/", views.api_mensagens_conversa, name="api_mensagens_conversa"),
    path("api/conversas/<int:conversa_id>/enviar/", views.api_enviar_mensagem_conversa, name="api_enviar_mensagem_conversa"),
    path("api/conversas/<int:conversa_id>/enviar-arquivo/", views.api_enviar_arquivo_conversa, name="api_enviar_arquivo_conversa"),
    path("api/conversas/<int:conversa_id>/marcar-lida/", views.api_marcar_conversa_lida, name="api_marcar_conversa_lida"),
    path("api/conversas/<int:conversa_id>/excluir/", views.api_excluir_conversa, name="api_excluir_conversa"),
    path("api/nova-conversa/", views.api_nova_conversa, name="api_nova_conversa"),
    path("webhook/", views.webhook_evento, name="webhook"),
]