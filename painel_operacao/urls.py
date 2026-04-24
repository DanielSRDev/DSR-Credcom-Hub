from django.urls import path
from . import views

app_name = "painel_operacao"

urlpatterns = [
    path("", views.painel_view, name="painel"),
    path("config/", views.config_view, name="config"),
    path("atualizar/", views.atualizar_view, name="atualizar"),
    path("exportar-excel/", views.exportar_excel_view, name="exportar_excel"),

    path("atualizar-relatorio-geral/", views.atualizar_relatorio_geral_view, name="atualizar_relatorio_geral"),
    path("exportar-relatorio-geral/", views.exportar_relatorio_geral_view, name="exportar_relatorio_geral"),
]