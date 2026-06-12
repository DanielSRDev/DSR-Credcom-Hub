from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("anotacoes/criar/", views.anotacao_criar, name="anotacao_criar"),
    path("anotacoes/<int:pk>/editar/", views.anotacao_editar, name="anotacao_editar"),
    path("anotacoes/<int:pk>/toggle/", views.anotacao_toggle, name="anotacao_toggle"),
    path("anotacoes/<int:pk>/fixar/", views.anotacao_fixar, name="anotacao_fixar"),
    path("anotacoes/<int:pk>/excluir/", views.anotacao_excluir, name="anotacao_excluir"),
]
