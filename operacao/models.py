from django.conf import settings
from django.db import models
from django.utils import timezone

class TarefaManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

class Equipe(models.Model):
    nome = models.CharField(max_length=80)
    ativa = models.BooleanField(default=True)

    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="operacao_equipes_supervisionadas",
    )
    membros = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="operacao_equipes",
    )

    class Meta:
        verbose_name = "Equipe (Operação)"
        verbose_name_plural = "Equipes (Operação)"

    def __str__(self):
        return f"{self.nome} (Supervisor: {getattr(self.supervisor, 'username', '-')})"


class Tarefa(models.Model):
    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        EXECUTANDO = "executando", "Executando"
        EXECUTADO = "executado", "Executado"
        FEITA = "feita", "Finalizada"

    titulo = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)

    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operacao_tarefas_criadas",
    )
    criada_em = models.DateTimeField(default=timezone.now)

    atribuida_para = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="operacao_tarefas_atribuidas",
    )

    prazo = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ABERTA)

    prioridade = models.BooleanField(default=False)
    ordem = models.PositiveIntegerField(default=0)

    # executor = quem marcou EXECUTANDO (pegou o chamado)
    executor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operacao_tarefas_executadas",
    )
    iniciado_em = models.DateTimeField(null=True, blank=True)
    executado_em = models.DateTimeField(null=True, blank=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["ordem", "-prazo", "-id"]
        verbose_name = "Tarefa (Operação)"
        verbose_name_plural = "Tarefas (Operação)"

    def __str__(self):
        return f"{self.titulo} [{self.get_status_display()}]"

    @property
    def esta_atrasada(self) -> bool:
        return self.status != self.Status.FEITA and timezone.now() > self.prazo

    @property
    def vencendo(self) -> bool:
        if self.status == self.Status.FEITA:
            return False
        delta = self.prazo - timezone.now()
        return 0 < delta.total_seconds() <= 24 * 3600
    # -----------------------
    # Lixeira (soft delete)
    # -----------------------
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="operacao_tarefas_deletadas",
    )

    # Por padrão, o sistema só enxerga NÃO deletadas
    objects = TarefaManager()
    # Para o admin ver TUDO (inclusive deletadas)
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

class Comentario(models.Model):
    tarefa = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="comentarios")
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operacao_comentarios_autor",
    )
    texto = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Comentário (Operação)"
        verbose_name_plural = "Comentários (Operação)"

    def __str__(self):
        return f"Comentário {self.id} - Tarefa {self.tarefa_id}"


class Anexo(models.Model):
    tarefa = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="anexos")
    arquivo = models.FileField(upload_to="operacao/anexos/")
    nome_original = models.CharField(max_length=255, blank=True)

    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operacao_anexos_enviados",
    )
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-enviado_em"]
        verbose_name = "Anexo (Operação)"
        verbose_name_plural = "Anexos (Operação)"

    def __str__(self):
        return f"Anexo {self.id} - Tarefa {self.tarefa_id}"