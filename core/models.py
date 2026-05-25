from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class PerfilUsuario(models.Model):
    """
    Perfil estendido do usuário.

    deve_trocar_senha = True  → usuário será redirecionado para criar
                                nova senha assim que fizer login.
    Admin pode marcar novamente para forçar troca (ex.: reset de senha).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil",
        verbose_name="Usuário",
    )
    deve_trocar_senha = models.BooleanField(
        default=True,
        verbose_name="Deve trocar senha no próximo acesso",
        help_text="Marque para forçar o usuário a criar nova senha no próximo login.",
    )

    class Meta:
        verbose_name = "Perfil de usuário"
        verbose_name_plural = "Perfis de usuários"

    def __str__(self):
        return f"Perfil de {self.user.username}"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_perfil_usuario(sender, instance, created, **kwargs):
    """Cria o perfil automaticamente quando um novo usuário é criado."""
    if created:
        PerfilUsuario.objects.get_or_create(user=instance)


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