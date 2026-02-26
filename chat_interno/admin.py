from django.contrib import admin
from .models import Conversation, Message, ChatVinculoOperador


@admin.register(ChatVinculoOperador)
class ChatVinculoOperadorAdmin(admin.ModelAdmin):
    list_display = ("operador", "supervisor", "criado_em")
    search_fields = ("operador__username", "supervisor__username")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user1", "user2", "criada_em")
    search_fields = ("user1__username", "user2__username")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "criado_em", "lido_em")
    search_fields = ("texto", "sender__username")
    list_filter = ("criado_em",)