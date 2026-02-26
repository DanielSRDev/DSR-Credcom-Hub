from django.conf import settings
from django.db import models
from django.db.models import Q

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
    texto = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)
    lido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["criado_em"]

    def __str__(self):
        return f"Msg {self.id} ({self.sender_id})"


class ChatVinculoOperador(models.Model):
    """
    OPERACAO -> Supervisor responsável.
    """
    operador = models.OneToOneField(User, on_delete=models.CASCADE, related_name="chat_vinculo_operador")
    supervisor = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_supervisionados")
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.operador} -> {self.supervisor}"