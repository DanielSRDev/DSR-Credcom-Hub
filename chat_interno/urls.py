from django.urls import path
from . import views

app_name = "chat_interno"

urlpatterns = [
    path("", views.index, name="index"),
    path("ping/", views.ping, name="ping"),
    path("contacts/", views.contacts, name="contacts"),
    path("history/<int:user_id>/", views.history, name="history"),
    path("send/<int:user_id>/", views.send_message, name="send"),
    path("mark_read/<int:user_id>/", views.mark_read, name="mark_read"),
    path("unread_total/", views.unread_total, name="unread_total"),
]