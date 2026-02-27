from django.contrib import admin
from django.contrib.auth import get_user_model
from django.http import HttpResponse
import csv

from .models import Conversation, Message, ChatVinculoOperador

User = get_user_model()


@admin.register(ChatVinculoOperador)
class ChatVinculoOperadorAdmin(admin.ModelAdmin):
    list_display = ("operador", "supervisor", "criado_em")
    search_fields = ("operador__username", "supervisor__username")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user1", "user2", "criada_em")
    search_fields = ("user1__username", "user2__username")


class Usuario1Filter(admin.SimpleListFilter):
    title = "Usuário 1"
    parameter_name = "u1"

    def lookups(self, request, model_admin):
        return [(u.username, u.username) for u in User.objects.all().order_by("username")]

    def queryset(self, request, queryset):
        return queryset


class Usuario2Filter(admin.SimpleListFilter):
    title = "Usuário 2"
    parameter_name = "u2"

    def lookups(self, request, model_admin):
        return [(u.username, u.username) for u in User.objects.all().order_by("username")]

    def queryset(self, request, queryset):
        return queryset


@admin.action(description="Exportar conversa entre usuários")
def exportar_conversa(modeladmin, request, queryset):
    u1 = request.GET.get("u1")
    u2 = request.GET.get("u2")

    if not u1 or not u2:
        modeladmin.message_user(request, "Selecione Usuário 1 e Usuário 2 nos filtros da direita.")
        return None

    try:
        user1 = User.objects.get(username=u1)
        user2 = User.objects.get(username=u2)
    except User.DoesNotExist:
        modeladmin.message_user(request, "Usuário inválido.")
        return None

    msgs = Message.objects.filter(
        sender__in=[user1, user2],
        conversation__user1__in=[user1, user2],
        conversation__user2__in=[user1, user2],
    ).select_related("conversation", "sender").order_by("criado_em")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="chat_{u1}_{u2}.csv"'

    writer = csv.writer(response)
    writer.writerow(["data", "de", "para", "mensagem"])

    for m in msgs:
        # Descobrir "para" (o outro usuário da conversa)
        other = m.conversation.user2 if m.sender_id == m.conversation.user1_id else m.conversation.user1

        writer.writerow([
            m.criado_em.strftime("%Y-%m-%d %H:%M:%S"),
            m.sender.username,
            other.username,
            (m.texto or "").replace("\n", " ").strip(),
        ])

    return response


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "criado_em", "lido_em")
    search_fields = ("texto", "sender__username", "conversation__user1__username", "conversation__user2__username")
    list_filter = ("criado_em", Usuario1Filter, Usuario2Filter)
    actions = [exportar_conversa]