# Gestao/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone

class TarefaManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Tarefa(models.Model):
    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        EXECUTANDO = "executando", "Executando"
        EXECUTADO = "executado", "Executado"
        FEITA = "feita", "Feita"

    titulo = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)
    prazo = models.DateTimeField()

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ABERTA,
    )

    atribuida_para = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tarefas_atribuidas",
    )

    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tarefas_criadas",
    )

    # quem clicou em "Executando" (normalmente = atribuida_para)
    executor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tarefas_em_execucao",
    )

    prioridade = models.BooleanField(default=False)

    ordem = models.PositiveIntegerField(default=0)

    criada_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    iniciado_em = models.DateTimeField(null=True, blank=True)
    executado_em = models.DateTimeField(null=True, blank=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)

    # -----------------------
    # Lixeira (soft delete)
    # -----------------------
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="gestao_tarefas_deletadas",
    )

    objects = TarefaManager()
    all_objects = models.Manager()

    def soft_delete(self, user=None):
        if self.deleted_at:
            return
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=["deleted_at", "deleted_by"])

    def restore(self):
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["deleted_at", "deleted_by"])
    # -----------------------
    # Regras de tempo/status
    # -----------------------
    @property
    def esta_atrasada(self):
        # tudo que não está finalizado oficialmente pode atrasar
        if self.status == self.Status.FEITA:
            return False
        return timezone.now() > self.prazo

    @property
    def vencendo(self):
        if self.status == self.Status.FEITA:
            return False
        agora = timezone.now()
        return agora <= self.prazo <= (agora + timezone.timedelta(hours=6))

    def iniciar_execucao(self, user=None):
        self.status = self.Status.EXECUTANDO
        if user and not self.executor:
            self.executor = user
        if not self.iniciado_em:
            self.iniciado_em = timezone.now()
        # se estava executado e voltou pra executando, limpa executado_em
        self.executado_em = None
        # se estava feita e reabriu, limpa finalizado_em
        self.finalizado_em = None

    def marcar_executado(self):
        self.status = self.Status.EXECUTADO
        if not self.executado_em:
            self.executado_em = timezone.now()
        # não finaliza aqui
        self.finalizado_em = None

    def finalizar(self):
        self.status = self.Status.FEITA
        if not self.finalizado_em:
            self.finalizado_em = timezone.now()

    def reabrir(self):
        self.status = self.Status.ABERTA
        self.iniciado_em = None
        self.executado_em = None
        self.finalizado_em = None
        self.executor = None


class Anexo(models.Model):
    tarefa = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="anexos")
    arquivo = models.FileField(upload_to="gestao/anexos/")
    nome_original = models.CharField(max_length=255, blank=True)

    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    texto = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Comentario({self.id}) tarefa {self.tarefa_id}"