from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpResponse
import csv

from .models import (
    Conversation,
    Message,
    ChatVinculoOperador,
    ChatMonitorConfig,
    ChatBloqueio,
    ChatLiberacao,
    ChatLiberacaoGrupo,
)

User = get_user_model()


@admin.register(ChatVinculoOperador)
class ChatVinculoOperadorAdmin(admin.ModelAdmin):
    list_display  = ("operador", "supervisor", "criado_em")
    search_fields = ("operador__username", "supervisor__username")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display  = ("id", "user1", "user2", "criada_em")
    search_fields = ("user1__username", "user2__username")


class Usuario1Filter(admin.SimpleListFilter):
    title           = "Usuário 1"
    parameter_name  = "u1"

    def lookups(self, request, model_admin):
        return [(u.username, u.username) for u in User.objects.all().order_by("username")]

    def queryset(self, request, queryset):
        return queryset


class Usuario2Filter(admin.SimpleListFilter):
    title           = "Usuário 2"
    parameter_name  = "u2"

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
    list_display  = ("id", "conversation", "sender", "criado_em", "lido_em")
    search_fields = ("texto", "sender__username", "conversation__user1__username", "conversation__user2__username")
    list_filter   = ("criado_em", Usuario1Filter, Usuario2Filter)
    actions       = [exportar_conversa]


class ChatMonitorConfigInline(admin.StackedInline):
    model      = ChatMonitorConfig
    can_delete = False
    extra      = 0
    fields     = ("monitorado", "notificar_fone", "pode_enviar_massa")


class ChatVinculoOperadorInline(admin.TabularInline):
    """
    Inline para gerenciar os vínculos operador -> supervisor(es)
    diretamente na página do usuário no admin.
    """
    model        = ChatVinculoOperador
    fk_name      = "operador"
    extra        = 1
    verbose_name = "Supervisor vinculado"
    verbose_name_plural = "Supervisores vinculados"
    raw_id_fields = ["supervisor"]


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class CustomUserAdmin(DjangoUserAdmin):
    inlines = [ChatMonitorConfigInline, ChatVinculoOperadorInline]


# ──────────────────────────────────────────────────────────────────────────────
# ChatBloqueio
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(ChatBloqueio)
class ChatBloqueioAdmin(admin.ModelAdmin):
    list_display    = ("par_display", "motivo", "criado_em")
    search_fields   = (
        "user_a__username", "user_a__first_name",
        "user_b__username", "user_b__first_name",
        "motivo",
    )
    readonly_fields     = ("criado_em",)
    autocomplete_fields = ("user_a", "user_b")
    ordering            = ("user_a__username",)
    actions             = ["liberar_chat"]

    @admin.action(description="✅ Liberar chat entre os usuários selecionados")
    def liberar_chat(self, request, queryset):
        total = queryset.count()
        queryset.delete()
        self.message_user(
            request,
            f"{total} bloqueio(s) removido(s). O chat entre os pares foi liberado.",
            level="success",
        )

    fieldsets = (
        (None, {
            "fields": ("user_a", "user_b", "motivo"),
            "description": (
                "Bloqueio bidirecional: nenhum dos dois aparece na lista do outro "
                "e nenhum consegue enviar mensagem. Superuser não é afetado."
            ),
        }),
        ("Auditoria", {
            "fields": ("criado_em",),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Par bloqueado")
    def par_display(self, obj):
        from django.utils.html import format_html
        return format_html(
            "<strong>{}</strong> &nbsp;↔&nbsp; <strong>{}</strong>",
            obj.user_a.get_full_name() or obj.user_a.username,
            obj.user_b.get_full_name() or obj.user_b.username,
        )

    def save_model(self, request, obj, form, change):
        if obj.user_a_id and obj.user_b_id and obj.user_a_id > obj.user_b_id:
            obj.user_a_id, obj.user_b_id = obj.user_b_id, obj.user_a_id
        super().save_model(request, obj, form, change)


# ──────────────────────────────────────────────────────────────────────────────
# ChatLiberacao
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(ChatLiberacao)
class ChatLiberacaoAdmin(admin.ModelAdmin):
    list_display    = ("par_display", "motivo", "criado_em")
    search_fields   = (
        "user_a__username", "user_a__first_name",
        "user_b__username", "user_b__first_name",
        "motivo",
    )
    readonly_fields     = ("criado_em",)
    autocomplete_fields = ("user_a", "user_b")
    ordering            = ("user_a__username",)
    actions             = ["revogar_liberacao"]

    @admin.action(description="🚫 Revogar liberação entre os usuários selecionados")
    def revogar_liberacao(self, request, queryset):
        total = queryset.count()
        queryset.delete()
        self.message_user(
            request,
            f"{total} liberação(ões) revogada(s). As regras de cargo voltam a valer.",
            level="warning",
        )

    fieldsets = (
        (None, {
            "fields": ("user_a", "user_b", "motivo"),
            "description": (
                "Liberação bidirecional: os dois se enxergam e podem trocar mensagens, "
                "independente do cargo ou grupo. "
                "Tem precedência sobre bloqueios: se existir liberação, o bloqueio é ignorado."
            ),
        }),
        ("Auditoria", {
            "fields": ("criado_em",),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Par liberado")
    def par_display(self, obj):
        from django.utils.html import format_html
        return format_html(
            "<strong>{}</strong> &nbsp;↔&nbsp; <strong>{}</strong>",
            obj.user_a.get_full_name() or obj.user_a.username,
            obj.user_b.get_full_name() or obj.user_b.username,
        )

    def save_model(self, request, obj, form, change):
        if obj.user_a_id and obj.user_b_id and obj.user_a_id > obj.user_b_id:
            obj.user_a_id, obj.user_b_id = obj.user_b_id, obj.user_a_id
        super().save_model(request, obj, form, change)


# ──────────────────────────────────────────────────────────────────────────────
# ChatLiberacaoGrupo (Grupão)
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(ChatLiberacaoGrupo)
class ChatLiberacaoGrupoAdmin(admin.ModelAdmin):
    list_display    = ("liberacao_display", "para_todos", "qtd_membros", "motivo", "criado_em")
    search_fields   = (
        "usuario__username", "usuario__first_name",
        "membros__username", "membros__first_name",
        "motivo",
    )
    readonly_fields     = ("criado_em",)
    autocomplete_fields = ("usuario",)
    filter_horizontal   = ("membros",)
    ordering            = ("usuario__username",)
    actions             = ["revogar_liberacao_grupo"]

    @admin.action(description="🚫 Revogar liberação em grupo selecionada")
    def revogar_liberacao_grupo(self, request, queryset):
        total = queryset.count()
        queryset.delete()
        self.message_user(
            request,
            f"{total} liberação(ões) em grupo revogada(s).",
            level="warning",
        )

    fieldsets = (
        (None, {
            "fields": ("usuario", "para_todos", "membros", "motivo"),
            "description": (
                "<strong>Grupão:</strong> selecione o <em>Usuário central</em> (ex: Leidiane do RH) "
                "e depois os <em>Membros</em> que poderão conversar individualmente com ela. "
                "Marque <em>Liberar para todos</em> para incluir todos os usuários ativos automaticamente "
                "(nesse caso, o campo Membros é ignorado). "
                "As conversas continuam sendo 1:1 — não é um grupo de chat."
            ),
        }),
        ("Auditoria", {
            "fields": ("criado_em",),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Usuário central ↔ Membros")
    def liberacao_display(self, obj):
        from django.utils.html import format_html
        usuario_nome = obj.usuario.get_full_name() or obj.usuario.username
        if obj.para_todos:
            detalhe = format_html("<em>Todos os usuários</em>")
        else:
            nomes = ", ".join(
                m.get_full_name() or m.username
                for m in obj.membros.all()[:5]
            )
            detalhe = format_html("{}", nomes or "—")
        return format_html("<strong>{}</strong> &nbsp;↔&nbsp; {}", usuario_nome, detalhe)

    @admin.display(description="Nº membros")
    def qtd_membros(self, obj):
        if obj.para_todos:
            return "Todos"
        return obj.membros.count()