from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Conversation(models.Model):
    """
    Conversa 1:1.
    Sempre guardamos user1_id < user2_id para evitar duplicidade.
    """
    user1 = models.ForeignKey(User, on_delete=models.CASCADE, related_name="conversations_as_user1")
    user2 = models.ForeignKey(User, on_delete=models.CASCADE, related_name="conversations_as_user2")
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user1", "user2"], name="uniq_conversation_user1_user2"),
        ]

    def __str__(self):
        return f"Conversa {self.user1_id} <-> {self.user2_id}"

    def other(self, user):
        return self.user2 if user == self.user1 else self.user1


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_messages")

    texto = models.TextField(blank=True, default="")
    imagem = models.ImageField(upload_to="chat_interno/imagens/", null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    lido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["criado_em"]

    def __str__(self):
        return f"Msg {self.id} ({self.sender_id})"


class ChatVinculoOperador(models.Model):
    """
    Vínculo OPERACAO -> Supervisor(es) responsável(is).

    Um operador pode ter múltiplos supervisores vinculados.
    A unicidade é garantida pelo par (operador, supervisor),
    impedindo vínculos duplicados para o mesmo par.
    """
    operador = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="chat_vinculos_operador",   # era: chat_vinculo_operador (OneToOne)
    )
    supervisor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="chat_supervisionados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operador", "supervisor"],
                name="uniq_chat_vinculo_operador_supervisor",
            ),
        ]
        verbose_name = "Vínculo operador-supervisor"
        verbose_name_plural = "Vínculos operador-supervisor"

    def __str__(self):
        return f"{self.operador} -> {self.supervisor}"


class ChatPresence(models.Model):

    class Status(models.TextChoices):
        ONLINE = "online", "Online"
        AUSENTE = "ausente", "Ausente"
        OFFLINE = "offline", "Offline"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_presence"
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OFFLINE
    )

    updated_at = models.DateTimeField(auto_now=True)


class ChatMonitorConfig(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_monitor_config"
    )
    can_monitor = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user} monitor={self.can_monitor}"

class ChatBloqueio(models.Model):
    """
    Bloqueio bidirecional de chat entre dois usuários.

    Se existir um registro (user_a, user_b), nenhum dos dois
    aparece na lista de contatos do outro e nenhum consegue
    enviar mensagem para o outro — independente do cargo/grupo.

    Sempre gravamos user_a_id < user_b_id para evitar duplicidade
    (mesma convenção usada em Conversation).

    Superuser não é afetado — vê e fala com todos.
    """
    user_a = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="chat_bloqueios_como_a",
        verbose_name="Usuário A",
    )
    user_b = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="chat_bloqueios_como_b",
        verbose_name="Usuário B",
    )
    motivo = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Motivo (opcional)",
        help_text="Registro interno — não exibido aos usuários.",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bloqueio de chat entre usuários"
        verbose_name_plural = "Bloqueios de chat entre usuários"
        constraints = [
            models.UniqueConstraint(
                fields=["user_a", "user_b"],
                name="uniq_chat_bloqueio_par",
            ),
        ]
        ordering = ["user_a__username", "user_b__username"]

    def __str__(self):
        return f"{self.user_a.username} ↔ {self.user_b.username} (bloqueado)"

    @classmethod
    def criar(cls, user1, user2, motivo=""):
        """
        Cria o bloqueio garantindo que user_a_id < user_b_id.
        Usa get_or_create para ser idempotente.
        """
        a, b = (user1, user2) if user1.id < user2.id else (user2, user1)
        obj, created = cls.objects.get_or_create(
            user_a=a, user_b=b,
            defaults={"motivo": motivo},
        )
        return obj, created

    @classmethod
    def existe(cls, user1, user2) -> bool:
        """Verifica se o par está bloqueado (em qualquer ordem)."""
        a_id, b_id = sorted([user1.id, user2.id])
        return cls.objects.filter(user_a_id=a_id, user_b_id=b_id).exists()