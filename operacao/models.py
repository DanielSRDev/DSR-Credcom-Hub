# operacao/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone


class TarefaManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Equipe(models.Model):
    nome  = models.CharField(max_length=80)
    ativa = models.BooleanField(default=True)

    supervisores = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="operacao_equipes_supervisionadas",
        verbose_name="Supervisores",
    )
    membros = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="operacao_equipes",
    )

    class Meta:
        verbose_name        = "Equipe (Operação)"
        verbose_name_plural = "Equipes (Operação)"

    def __str__(self):
        nomes = ", ".join(self.supervisores.values_list("username", flat=True)) or "-"
        return f"{self.nome} (Supervisores: {nomes})"


class Tarefa(models.Model):
    class Status(models.TextChoices):
        ABERTA     = "aberta",    "Aberta"
        EXECUTANDO = "executando","Executando"
        EXECUTADO  = "executado", "Executado"
        PENDENTE   = "pendente",  "Pendente de validação"   # NOVO
        FEITA      = "feita",     "Finalizada"

    # ------------------------------------------------------------------
    # Identificação
    # ------------------------------------------------------------------
    codigo = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Código",
        help_text="Identificador único do chamado (ex: OPE-00001). Gerado automaticamente.",
        blank=True,
    )

    titulo    = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)

    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="operacao_tarefas_criadas",
    )
    criada_em = models.DateTimeField(default=timezone.now)

    atribuida_para = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="operacao_tarefas_atribuidas",
    )

    prazo  = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ABERTA)

    prioridade = models.BooleanField(default=False)
    ordem      = models.PositiveIntegerField(default=0)

    executor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="operacao_tarefas_executadas",
    )
    iniciado_em   = models.DateTimeField(null=True, blank=True)
    executado_em  = models.DateTimeField(null=True, blank=True)
    pendente_em   = models.DateTimeField(null=True, blank=True)   # NOVO
    finalizado_em = models.DateTimeField(null=True, blank=True)

    # Marca cards fechados pela varredura automática (prazo de validação estourado)
    finalizado_automaticamente = models.BooleanField(default=False)

    # ------------------------------------------------------------------
    # Soft delete
    # ------------------------------------------------------------------
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="operacao_tarefas_deletadas",
    )

    objects     = TarefaManager()
    all_objects = models.Manager()

    class Meta:
        ordering        = ["ordem", "-prazo", "-id"]
        verbose_name        = "Tarefa (Operação)"
        verbose_name_plural = "Tarefas (Operação)"

    def __str__(self):
        return f"{self.titulo} [{self.get_status_display()}]"

    # ------------------------------------------------------------------
    # Geração automática do código
    # ------------------------------------------------------------------
    def save(self, *args, **kwargs):
        _update_fields = kwargs.get("update_fields")
        if not self.pk and not self.codigo:
            super().save(*args, **kwargs)
            self.codigo = f"OPE-{self.pk:05d}"
            self.save(update_fields=["codigo"])
            return
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Propriedades de tempo
    # ------------------------------------------------------------------
    @property
    def esta_atrasada(self) -> bool:
        if self.status not in {self.Status.ABERTA, self.Status.EXECUTANDO, self.Status.PENDENTE}:
            return False
        return timezone.now() > self.prazo

    @property
    def vencendo(self) -> bool:
        if self.status not in {self.Status.ABERTA, self.Status.EXECUTANDO, self.Status.PENDENTE}:
            return False
        delta = self.prazo - timezone.now()
        return 0 < delta.total_seconds() <= 24 * 3600

    # ------------------------------------------------------------------
    # Transições de status
    # ------------------------------------------------------------------
    def marcar_pendente(self):
        self.status = self.Status.PENDENTE
        if not self.pendente_em:
            self.pendente_em = timezone.now()
        self.finalizado_em = None

    def devolver_execucao(self):
        self.status = self.Status.EXECUTANDO
        self.executado_em  = None
        self.pendente_em   = None
        self.finalizado_em = None

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
    tarefa    = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="comentarios")
    autor     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="operacao_comentarios_autor",
    )
    texto        = models.TextField()
    criado_em    = models.DateTimeField(auto_now_add=True)
    eh_devolucao = models.BooleanField(default=False)   # NOVO

    class Meta:
        ordering        = ["-criado_em"]
        verbose_name        = "Comentário (Operação)"
        verbose_name_plural = "Comentários (Operação)"

    def __str__(self):
        return f"Comentário {self.id} - Tarefa {self.tarefa_id}"


class Anexo(models.Model):
    tarefa        = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="anexos")
    arquivo       = models.FileField(upload_to="operacao/anexos/")
    nome_original = models.CharField(max_length=255, blank=True)
    enviado_por   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="operacao_anexos_enviados",
    )
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering        = ["-enviado_em"]
        verbose_name        = "Anexo (Operação)"
        verbose_name_plural = "Anexos (Operação)"

    def __str__(self):
        return f"Anexo {self.id} - Tarefa {self.tarefa_id}"


class OperacaoPermissaoUsuario(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="operacao_permissao",
        verbose_name="Usuário",
    )
    bloquear_criar_chamado_supervisor = models.BooleanField(
        default=False,
        verbose_name="Bloquear criação de chamado para o supervisor",
        help_text=(
            "Por padrão, todos podem criar chamado para o supervisor. "
            "Marque para BLOQUEAR este usuário específico."
        ),
    )

    class Meta:
        verbose_name        = "Permissão de usuário (Operação)"
        verbose_name_plural = "Permissões de usuários (Operação)"

    def __str__(self):
        status = "BLOQUEADO" if self.bloquear_criar_chamado_supervisor else "PODE"
        return f"{self.user.username} - criar chamado p/ supervisor: {status}"
