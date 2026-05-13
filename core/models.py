from django.conf import settings
from django.db import models


class UsuarioRestricaoModulo(models.Model):
    """
    Blacklist de módulos por usuário.

    Mesmo que o usuário tenha o grupo que daria acesso ao módulo,
    se existir um registro aqui com modulo_bloqueado correspondente,
    o middleware negará o acesso e o context_processor ocultará o item
    da navbar.

    Superuser nunca é bloqueado — a checagem no middleware e no
    context_processor pula superusers explicitamente.
    """

    class Modulo(models.TextChoices):
        NIBO            = "nibo",            "Nibo Panel"
        GESTAO          = "gestao",          "Gestão"
        OPERACAO        = "operacao",        "Operação"
        ZAPMSG          = "zapmsg",          "ZapMsg (WhatsApp)"
        PAINEL_OPERACAO = "painel_operacao", "Painel Operação"
        CHAT            = "chat",            "Chat Interno"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="restricoes_modulo",
        verbose_name="Usuário",
    )
    modulo_bloqueado = models.CharField(
        max_length=30,
        choices=Modulo.choices,
        verbose_name="Módulo bloqueado",
    )
    motivo = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Motivo (opcional)",
        help_text="Registro interno — não exibido ao usuário.",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Restrição de módulo por usuário"
        verbose_name_plural = "Restrições de módulo por usuário"
        unique_together = ("user", "modulo_bloqueado")
        ordering = ["user__username", "modulo_bloqueado"]

    def __str__(self):
        return f"{self.user.username} — bloqueado: {self.get_modulo_bloqueado_display()}"