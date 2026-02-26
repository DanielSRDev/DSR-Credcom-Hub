from django.urls import path
from . import views

app_name = "chat_interno"

urlpatterns = [
    path("ping/", views.ping, name="ping"),
    path("contacts/", views.contacts, name="contacts"),
    path("thread/<int:user_id>/messages/", views.messages, name="messages"),
    path("thread/<int:user_id>/send/", views.send, name="send"),
]