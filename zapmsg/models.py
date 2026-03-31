import uuid
import os
from uuid import uuid4
from django.conf import settings
from django.db import models
from django.utils import timezone


def zap_media_upload_to(instance, filename):
    ext = os.path.splitext(filename or "")[1].lower()
    if not ext:
        ext = ".bin"
    return f"zapmsg/media/{uuid4().hex}{ext}"

def generate_session_id():
    return str(uuid.uuid4())

class ZapConta(models.Model):
    class Status(models.TextChoices):
        DESCONECTADO = "desconectado", "Desconectado"
        CONECTANDO = "conectando", "Conectando"
        AGUARDANDO_QR = "aguardando_qr", "Aguardando QR"
        CONECTADO = "conectado", "Conectado"
        ERRO = "erro", "Erro"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="zap_conta",
    )
    session_id = models.CharField(
        max_length=120,
        unique=True,
        default=generate_session_id,
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DESCONECTADO)
    telefone = models.CharField(max_length=30, blank=True, default="")
    nome_perfil = models.CharField(max_length=120, blank=True, default="")
    qr_code = models.TextField(blank=True, default="")
    ultimo_erro = models.TextField(blank=True, default="")
    conectado_em = models.DateTimeField(null=True, blank=True)
    ultimo_ping = models.DateTimeField(null=True, blank=True)

    criada_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.status}"


class ZapContato(models.Model):
    conta = models.ForeignKey(ZapConta, on_delete=models.CASCADE, related_name="contatos")
    wa_id = models.CharField(max_length=120)
    numero = models.CharField(max_length=30, blank=True, default="")
    nome = models.CharField(max_length=120, blank=True, default="")
    nome_exibicao = models.CharField(max_length=120, blank=True, default="")
    ultima_interacao_em = models.DateTimeField(null=True, blank=True)
    arquivado = models.BooleanField(default=False)
    bloqueado = models.BooleanField(default=False)

    criada_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("conta", "wa_id")
        ordering = ["-ultima_interacao_em", "-id"]

    @property
    def display_name(self):
        return self.nome_exibicao or self.nome or self.numero or self.wa_id

    def __str__(self):
        return self.display_name


class ZapConversa(models.Model):
    conta = models.ForeignKey(ZapConta, on_delete=models.CASCADE, related_name="conversas")
    contato = models.ForeignKey(ZapContato, on_delete=models.CASCADE, related_name="conversas")

    ultima_mensagem = models.TextField(blank=True, default="")
    ultima_mensagem_em = models.DateTimeField(null=True, blank=True)
    nao_lidas = models.PositiveIntegerField(default=0)

    fixada = models.BooleanField(default=False)
    arquivada = models.BooleanField(default=False)
    status_atendimento = models.CharField(max_length=30, blank=True, default="")

    criada_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("conta", "contato")
        ordering = ["-fixada", "-ultima_mensagem_em", "-id"]

    def atualizar_ultima_interacao(self, texto="", data=None, incrementar_nao_lidas=False):
        self.ultima_mensagem = texto or ""
        self.ultima_mensagem_em = data or timezone.now()
        if incrementar_nao_lidas:
            self.nao_lidas = (self.nao_lidas or 0) + 1
        self.save(update_fields=["ultima_mensagem", "ultima_mensagem_em", "nao_lidas", "atualizado_em"])

    def __str__(self):
        return f"{self.conta.user.username} -> {self.contato.display_name}"


class ZapMensagem(models.Model):
    class Direction(models.TextChoices):
        IN = "in", "Recebida"
        OUT = "out", "Enviada"

    class Tipo(models.TextChoices):
        TEXTO = "texto", "Texto"
        AUDIO = "audio", "Áudio"
        IMAGEM = "imagem", "Imagem"
        DOCUMENTO = "documento", "Documento"
        VIDEO = "video", "Vídeo"
        ARQUIVO = "arquivo", "Arquivo"

    class StatusEnvio(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ENVIADA = "enviada", "Enviada"
        ENTREGUE = "entregue", "Entregue"
        LIDA = "lida", "Lida"
        RECEBIDA = "recebida", "Recebida"
        ERRO = "erro", "Erro"

    conversa = models.ForeignKey(ZapConversa, on_delete=models.CASCADE, related_name="mensagens")
    externo_id = models.CharField(max_length=255, blank=True, default="", db_index=True)

    direction = models.CharField(max_length=10, choices=Direction.choices)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.TEXTO)
    status_envio = models.CharField(max_length=20, choices=StatusEnvio.choices, default=StatusEnvio.PENDENTE)

    texto = models.TextField(blank=True, default="")
    media_url = models.TextField(blank=True, default="")
    raw_payload = models.JSONField(default=dict, blank=True)

    enviada_em = models.DateTimeField(default=timezone.now)
    lida = models.BooleanField(default=False)

    criada_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["enviada_em", "id"]

    def __str__(self):
        return f"{self.get_direction_display()} - {self.texto[:40]}"