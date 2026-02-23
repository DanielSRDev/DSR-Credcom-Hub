# Gestao/models.py
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Tarefa(models.Model):
    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        EXECUTANDO = "executando", "Executando"
        FEITA = "feita", "Feita"

    titulo = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)

    prazo = models.DateTimeField()

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ABERTA
    )

    atribuida_para = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tarefas_atribuidas"
    )

    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="tarefas_criadas"
    )

    criada_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    iniciado_em = models.DateTimeField(null=True, blank=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)

    ordem = models.PositiveIntegerField(default=0)
    prioridade = models.BooleanField(default=False)

    @property
    def esta_atrasada(self):
        return self.status in (self.Status.ABERTA, self.Status.EXECUTANDO) and timezone.now() > self.prazo

    @property
    def vencendo(self):
        if self.status not in (self.Status.ABERTA, self.Status.EXECUTANDO):
            return False
        agora = timezone.now()
        return agora <= self.prazo <= (agora + timedelta(hours=6))

    def iniciar_execucao(self):
        self.status = self.Status.EXECUTANDO
        if not self.iniciado_em:
            self.iniciado_em = timezone.now()

    def parar_execucao(self):
        self.status = self.Status.ABERTA

    def finalizar(self):
        self.status = self.Status.FEITA
        if not self.finalizado_em:
            self.finalizado_em = timezone.now()


class Anexo(models.Model):
    tarefa = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="anexos")
    arquivo = models.FileField(upload_to="gestao/anexos/")
    nome_original = models.CharField(max_length=255, blank=True)

    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    enviado_em = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.arquivo and not self.nome_original:
            self.nome_original = self.arquivo.name.split("/")[-1].split("\\")[-1]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Anexo({self.nome_original}) - tarefa {self.tarefa_id}"


class Comentario(models.Model):
    tarefa = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="comentarios")
    texto = models.TextField()
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-criado_em",)

    def __str__(self):
        return f"Comentário #{self.id} tarefa {self.tarefa_id}"