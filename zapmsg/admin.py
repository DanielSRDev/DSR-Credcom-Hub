from django.contrib import admin
from .models import ZapConta, ZapContato, ZapConversa, ZapMensagem


@admin.register(ZapConta)
class ZapContaAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "status",
        "telefone",
        "nome_perfil",
        "conectado_em",
        "ultimo_ping",
        "session_id",
    )
    search_fields = (
        "user__username",
        "telefone",
        "nome_perfil",
        "session_id",
    )
    list_filter = (
        "status",
        "conectado_em",
    )
    readonly_fields = (
        "session_id",
        "qr_code",
        "conectado_em",
        "ultimo_ping",
        "criada_em",
        "atualizado_em",
    )


@admin.register(ZapContato)
class ZapContatoAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "conta",
        "numero",
        "wa_id",
        "ultima_interacao_em",
        "arquivado",
        "bloqueado",
    )
    search_fields = (
        "nome",
        "nome_exibicao",
        "numero",
        "wa_id",
        "conta__user__username",
    )
    list_filter = (
        "arquivado",
        "bloqueado",
        "ultima_interacao_em",
    )


@admin.register(ZapConversa)
class ZapConversaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "conta",
        "contato",
        "ultima_mensagem_resumo",
        "ultima_mensagem_em",
        "nao_lidas",
        "fixada",
        "arquivada",
    )
    search_fields = (
        "contato__nome",
        "contato__nome_exibicao",
        "contato__numero",
        "conta__user__username",
        "ultima_mensagem",
    )
    list_filter = (
        "fixada",
        "arquivada",
        "ultima_mensagem_em",
    )

    @admin.display(description="Última mensagem")
    def ultima_mensagem_resumo(self, obj):
        texto = obj.ultima_mensagem or ""
        return texto[:60]


@admin.register(ZapMensagem)
class ZapMensagemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "conversa",
        "direction",
        "status_envio",
        "texto_resumo",
        "enviada_em",
        "lida",
    )
    search_fields = (
        "texto",
        "externo_id",
        "conversa__contato__nome",
        "conversa__contato__nome_exibicao",
        "conversa__contato__numero",
        "conversa__conta__user__username",
    )
    list_filter = (
        "direction",
        "status_envio",
        "lida",
        "enviada_em",
    )
    readonly_fields = (
        "externo_id",
        "raw_payload",
        "criada_em",
        "atualizado_em",
    )

    @admin.display(description="Texto")
    def texto_resumo(self, obj):
        texto = obj.texto or ""
        return texto[:80]