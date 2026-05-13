from django.contrib import admin
from django.utils.html import format_html

from .models import UsuarioRestricaoModulo


class RestricaoInline(admin.TabularInline):
    model = UsuarioRestricaoModulo
    extra = 1
    fields = ("modulo_bloqueado", "motivo", "criado_em")
    readonly_fields = ("criado_em",)


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