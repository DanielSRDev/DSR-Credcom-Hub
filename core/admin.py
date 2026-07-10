import logging

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html

from .models import (
    AnotacaoPessoal,
    ConfiguracaoSeguranca,
    JornalPost,
    JornalReacao,
    JornalComentario,
    PerfilUsuario,
    UsuarioRestricaoModulo,
    UsuarioLiberacaoModulo,
)

logger = logging.getLogger("core.admin")


# ── Inlines ──────────────────────────────────────────────────────────────────

class PerfilInline(admin.StackedInline):
    model = PerfilUsuario
    can_delete = False
    verbose_name_plural = "Primeiro Acesso / Senha"
    fields = ("deve_trocar_senha", "pode_publicar_jornal")


class RestricaoInline(admin.TabularInline):
    model = UsuarioRestricaoModulo
    extra = 1
    fields = ("modulo_bloqueado", "motivo", "criado_em")
    readonly_fields = ("criado_em",)


class LiberacaoInline(admin.TabularInline):
    model = UsuarioLiberacaoModulo
    extra = 1
    fields = ("modulo_liberado", "motivo", "criado_em")
    readonly_fields = ("criado_em",)
    verbose_name = "Liberação de módulo (whitelist)"
    verbose_name_plural = "Liberações de módulo (libera módulo individualmente)"


# ── User Admin customizado ────────────────────────────────────────────────────

class CustomUserAdmin(BaseUserAdmin):
    inlines = [PerfilInline, RestricaoInline, LiberacaoInline]
    actions = ["marcar_primeiro_acesso", "desmarcar_primeiro_acesso"]
    list_display = BaseUserAdmin.list_display + ("status_primeiro_acesso",)

    # --- Coluna de status na listagem ----------------------------------------

    @admin.display(description="Primeiro acesso")
    def status_primeiro_acesso(self, obj):
        try:
            if obj.perfil.deve_trocar_senha:
                return format_html(
                    '<span style="background:#d97706;color:#fff;padding:2px 8px;'
                    'border-radius:4px;font-size:11px">⏳ Aguardando troca</span>'
                )
        except Exception:
            pass
        return format_html(
            '<span style="background:#16a34a;color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px">✔ OK</span>'
        )

    # --- Ações na lista de usuários ------------------------------------------

    @admin.action(description="Marcar para trocar senha no próximo login")
    def marcar_primeiro_acesso(self, request, queryset):
        total = 0
        for user in queryset:
            perfil, _ = PerfilUsuario.objects.get_or_create(user=user)
            perfil.deve_trocar_senha = True
            perfil.save(update_fields=["deve_trocar_senha"])
            total += 1
        self.message_user(
            request,
            f"{total} usuário(s) marcado(s) — precisarão criar nova senha no próximo login.",
        )

    @admin.action(description="Desmarcar troca de senha obrigatória")
    def desmarcar_primeiro_acesso(self, request, queryset):
        total = 0
        for user in queryset:
            perfil, _ = PerfilUsuario.objects.get_or_create(user=user)
            perfil.deve_trocar_senha = False
            perfil.save(update_fields=["deve_trocar_senha"])
            total += 1
        self.message_user(
            request,
            f"{total} usuário(s) desmarcado(s) — não precisarão trocar senha.",
        )

    # Nota: o flag deve_trocar_senha é setado automaticamente pelo signal
    # pre_save em core/models.py sempre que a senha do usuário muda.
    # O admin pode usar a ação "Marcar para trocar senha" para forçar manualmente.


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# ── UsuarioRestricaoModulo ────────────────────────────────────────────────────

@admin.register(UsuarioRestricaoModulo)
class UsuarioRestricaoModuloAdmin(admin.ModelAdmin):
    list_display = ("usuario_display", "modulo_display", "motivo", "criado_em")
    list_filter = ("modulo_bloqueado",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "motivo")
    autocomplete_fields = ("user",)
    readonly_fields = ("criado_em",)
    ordering = ("user__username", "modulo_bloqueado")

    fieldsets = (
        (None, {
            "fields": ("user", "modulo_bloqueado", "motivo"),
        }),
        ("Auditoria", {
            "fields": ("criado_em",),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Usuário", ordering="user__username")
    def usuario_display(self, obj):
        nome = obj.user.get_full_name() or obj.user.username
        return format_html("<strong>{}</strong> <small>({})</small>", nome, obj.user.username)

    @admin.display(description="Módulo bloqueado")
    def modulo_display(self, obj):
        cores = {
            "nibo":            "#0284c7",
            "gestao":          "#7c3aed",
            "operacao":        "#1d4ed8",
            "zapmsg":          "#b45309",
            "painel_operacao": "#374151",
            "chat":            "#065f46",
        }
        cor = cores.get(obj.modulo_bloqueado, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{}</span>',
            cor,
            obj.get_modulo_bloqueado_display(),
        )


@admin.register(UsuarioLiberacaoModulo)
class UsuarioLiberacaoModuloAdmin(admin.ModelAdmin):
    list_display = ("usuario_display", "modulo_display", "motivo", "criado_em")
    list_filter = ("modulo_liberado",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "motivo")
    autocomplete_fields = ("user",)
    readonly_fields = ("criado_em",)
    ordering = ("user__username", "modulo_liberado")

    fieldsets = (
        (None, {
            "fields": ("user", "modulo_liberado", "motivo"),
        }),
        ("Auditoria", {
            "fields": ("criado_em",),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Usuário", ordering="user__username")
    def usuario_display(self, obj):
        nome = obj.user.get_full_name() or obj.user.username
        return format_html("<strong>{}</strong> <small>({})</small>", nome, obj.user.username)

    @admin.display(description="Módulo liberado")
    def modulo_display(self, obj):
        cores = {
            "nibo":            "#0284c7",
            "gestao":          "#7c3aed",
            "operacao":        "#1d4ed8",
            "zapmsg":          "#b45309",
            "painel_operacao": "#374151",
            "chat":            "#065f46",
            "financeiro":      "#047857",
        }
        cor = cores.get(obj.modulo_liberado, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">✓ {}</span>',
            cor,
            obj.get_modulo_liberado_display(),
        )


@admin.register(JornalPost)
class JornalPostAdmin(admin.ModelAdmin):
    list_display = ("titulo", "autor", "criado_em", "editado_em")
    search_fields = ("titulo", "conteudo")
    readonly_fields = ("criado_em", "editado_em")
    ordering = ("-criado_em",)


@admin.register(JornalReacao)
class JornalReacaoAdmin(admin.ModelAdmin):
    list_display = ("emoji", "post", "comentario", "user", "criado_em")
    list_filter = ("emoji",)
    search_fields = ("post__titulo", "comentario__texto", "user__username")
    autocomplete_fields = ("post", "comentario", "user")


@admin.register(JornalComentario)
class JornalComentarioAdmin(admin.ModelAdmin):
    list_display = ("post", "user", "texto", "criado_em")
    search_fields = ("post__titulo", "user__username", "texto")
    readonly_fields = ("criado_em",)
    autocomplete_fields = ("post", "user")


@admin.register(AnotacaoPessoal)
class AnotacaoPessoalAdmin(admin.ModelAdmin):
    list_display = ("user", "texto", "cor", "fixada", "concluida", "lembrete_em", "criado_em")
    list_filter = ("concluida", "fixada", "cor")
    search_fields = ("user__username", "texto")
    autocomplete_fields = ("user",)


# ── ConfiguracaoSeguranca (singleton) ─────────────────────────────────────────

class ConfiguracaoSegurancaForm(forms.ModelForm):
    nova_senha = forms.CharField(
        label="Nova senha de reabertura",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Preencha apenas para definir/alterar. Deixe em branco para manter a atual.",
    )

    class Meta:
        model = ConfiguracaoSeguranca
        fields = ("prazo_validacao_dias", "nova_senha")

    def save(self, commit=True):
        obj = super().save(commit=False)
        nova = self.cleaned_data.get("nova_senha")
        if nova:
            obj.set_senha(nova)
        if commit:
            obj.save()
        return obj


@admin.register(ConfiguracaoSeguranca)
class ConfiguracaoSegurancaAdmin(admin.ModelAdmin):
    form = ConfiguracaoSegurancaForm
    list_display = ("__str__", "prazo_validacao_dias", "senha_definida", "atualizado_em")
    readonly_fields = ("atualizado_em",)

    @admin.display(description="Senha definida", boolean=True)
    def senha_definida(self, obj):
        return bool(obj.senha_reabertura)

    def has_add_permission(self, request):
        # Singleton: só permite adicionar se ainda não existe registro.
        return not ConfiguracaoSeguranca.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
