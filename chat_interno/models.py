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
    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies"
    )

    texto = models.TextField(blank=True, default="")
    imagem = models.ImageField(upload_to="chat_interno/imagens/", null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    lido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["criado_em"]

    def __str__(self):
        return f"Msg {self.id} ({self.sender_id})"


class MessageReaction(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_reactions")
    emoji = models.CharField(max_length=10)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["message", "user", "emoji"], name="uniq_message_reaction"
            )
        ]

    def __str__(self):
        return f"{self.emoji} por {self.user_id} em msg {self.message_id}"


class ChatVinculoOperador(models.Model):
    """
    Vínculo OPERACAO -> Supervisor(es) responsável(is).
    Um operador pode ter múltiplos supervisores vinculados.
    """
    operador   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="vinculos_como_operador")
    supervisor = models.ForeignKey(User, on_delete=models.CASCADE, related_name="vinculos_como_supervisor")
    criado_em  = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["operador", "supervisor"], name="uniq_vinculo_operador_supervisor"),
        ]
        verbose_name        = "Vínculo operador-supervisor"
        verbose_name_plural = "Vínculos operador-supervisor"

    def __str__(self):
        return f"{self.operador} → {self.supervisor}"


class ChatPresence(models.Model):
    class Status(models.TextChoices):
        ONLINE  = "online",  "Online"
        AUSENTE = "ausente", "Ausente"
        OFFLINE = "offline", "Offline"

    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name="chat_presence")
    status     = models.CharField(max_length=10, choices=Status.choices, default=Status.OFFLINE)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} [{self.status}]"


class ChatMonitorConfig(models.Model):
    user           = models.OneToOneField(User, on_delete=models.CASCADE, related_name="chat_monitor_config")
    monitorado     = models.BooleanField(default=False)
    notificar_fone = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        verbose_name        = "Configuração de monitor"
        verbose_name_plural = "Configurações de monitor"

    def __str__(self):
        return f"Monitor: {self.user}"


class ChatBloqueio(models.Model):
    """
    Bloqueio bidirecional de chat entre dois usuários.

    Se existir um registro (user_a, user_b), nenhum dos dois
    aparece na lista de contatos do outro e nenhum consegue
    enviar mensagem — independente do cargo/grupo.

    Sempre gravamos user_a_id < user_b_id para evitar duplicidade.
    Superuser não é afetado.
    """
    user_a    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_bloqueios_como_a", verbose_name="Usuário A")
    user_b    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_bloqueios_como_b", verbose_name="Usuário B")
    motivo    = models.CharField(max_length=255, blank=True, verbose_name="Motivo (opcional)")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Bloqueio de chat entre usuários"
        verbose_name_plural = "Bloqueios de chat entre usuários"
        ordering            = ["user_a__username", "user_b__username"]
        constraints         = [
            models.UniqueConstraint(fields=["user_a", "user_b"], name="uniq_chat_bloqueio_par"),
        ]

    def __str__(self):
        return f"Bloqueio: {self.user_a} ↔ {self.user_b}"

    @classmethod
    def criar(cls, user1, user2, motivo=""):
        a, b = (user1, user2) if user1.id < user2.id else (user2, user1)
        obj, created = cls.objects.get_or_create(user_a=a, user_b=b, defaults={"motivo": motivo})
        return obj, created

    @classmethod
    def existe(cls, user1, user2) -> bool:
        a_id, b_id = sorted([user1.id, user2.id])
        return cls.objects.filter(user_a_id=a_id, user_b_id=b_id).exists()


class ChatLiberacao(models.Model):
    """
    Liberação explícita de chat entre dois usuários.

    Fura a regra de cargo/grupo: se existir um registro (user_a, user_b),
    os dois se enxergam na lista de contatos e podem trocar mensagens,
    independente dos grupos a que pertencem.

    Exemplos de uso:
    - Operador que precisa falar diretamente com um gestor.
    - Dois usuários de grupos distintos que precisam se comunicar pontualmente.

    Sempre gravamos user_a_id < user_b_id para evitar duplicidade.
    Superuser não precisa de liberação — já vê todos.

    PRIORIDADE: ChatLiberacao tem precedência sobre ChatBloqueio.
    Se existir liberação entre A e B, o bloqueio é ignorado.
    """
    user_a    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_liberacoes_como_a", verbose_name="Usuário A")
    user_b    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_liberacoes_como_b", verbose_name="Usuário B")
    motivo    = models.CharField(max_length=255, blank=True, verbose_name="Motivo (opcional)")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Liberação de chat entre usuários"
        verbose_name_plural = "Liberações de chat entre usuários"
        ordering            = ["user_a__username", "user_b__username"]
        constraints         = [
            models.UniqueConstraint(fields=["user_a", "user_b"], name="uniq_chat_liberacao_par"),
        ]

    def __str__(self):
        return f"Liberação: {self.user_a} ↔ {self.user_b}"

    @classmethod
    def criar(cls, user1, user2, motivo=""):
        a, b = (user1, user2) if user1.id < user2.id else (user2, user1)
        obj, created = cls.objects.get_or_create(user_a=a, user_b=b, defaults={"motivo": motivo})
        return obj, created

    @classmethod
    def existe(cls, user1, user2) -> bool:
        a_id, b_id = sorted([user1.id, user2.id])
        return cls.objects.filter(user_a_id=a_id, user_b_id=b_id).exists()