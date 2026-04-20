from django.urls import path
from . import views

app_name = "painel_operacao"

urlpatterns = [
    path("", views.painel_view, name="painel"),
    path("config/", views.config_view, name="config"),
    path("atualizar/", views.atualizar_view, name="atualizar"),
]