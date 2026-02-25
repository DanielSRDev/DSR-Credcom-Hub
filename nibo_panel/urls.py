# nibo_panel/urls.py
from django.urls import path
from . import views

app_name = "nibo_panel"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("enviar/", views.enviar_remessa, name="enviar"),
    
]
