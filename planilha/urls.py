from django.urls import path

from . import views

app_name = "planilha"

urlpatterns = [
    path("", views.index, name="index"),
    path("busca-global/", views.busca_global, name="busca_global"),
    path("sincronizar-status/", views.sincronizar_status_agora, name="sincronizar_status_agora"),
    path("importar/", views.importar, name="importar"),
    path("importar/confirmar/", views.confirmar_importacao, name="confirmar_importacao"),
    path("devolucao/<str:nome>/", views.baixar_devolucao, name="baixar_devolucao"),

    path("contrato/<int:pk>/", views.contrato_detalhe, name="contrato_detalhe"),
    path("contrato/<int:pk>/card/", views.contrato_card, name="contrato_card"),
    path("exportar-selecionados/", views.exportar_selecionados, name="exportar_selecionados"),
    path("exportar-filtrados/", views.exportar_filtrados, name="exportar_filtrados"),
    path("prioridade-lote/", views.prioridade_lote, name="prioridade_lote"),
    path("destaque-lote/", views.destaque_lote, name="destaque_lote"),
    path("fila-lote/", views.fila_lote, name="fila_lote"),
    path("contrato/<int:pk>/prioridade/", views.toggle_prioridade, name="toggle_prioridade"),
    path("contrato/<int:pk>/destaque/", views.definir_destaque, name="definir_destaque"),
    path("contrato/<int:pk>/acrescimo/", views.adicionar_acrescimo, name="adicionar_acrescimo"),
    path("acrescimo/<int:pk>/excluir/", views.excluir_acrescimo, name="excluir_acrescimo"),
    path("contrato/<int:pk>/acionamento/", views.registrar_acionamento, name="registrar_acionamento"),
    path("contrato/<int:pk>/sair-da-fila/", views.sair_da_fila, name="sair_da_fila"),
]
