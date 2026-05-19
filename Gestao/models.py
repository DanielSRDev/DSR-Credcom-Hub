# Gestao/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone


class TarefaManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Tarefa(models.Model):
    class Status(models.TextChoices):
        ABERTA      = "aberta",    "Aberta"
        EXECUTANDO  = "executando","Executando"
        EXECUTADO   = "executado", "Executado"
        PENDENTE    = "pendente",  "Pendente de validação"   # NOVO
        FEITA       = "feita",     "Feita"

    # ------------------------------------------------------------------
    # Identificação
    # ------------------------------------------------------------------
    codigo = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Código",
        help_text="Identificador único do card (ex: GES-00001). Gerado automaticamente.",
        blank=True,
    )

    titulo    = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)
    prazo     = models.DateTimeField()

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
        null=True, blank=True,
        related_name="tarefas_criadas",
    )
    executor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="tarefas_em_execucao",
    )

    prioridade = models.BooleanField(default=False)
    ordem      = models.PositiveIntegerField(default=0)

    criada_em     = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    iniciado_em   = models.DateTimeField(null=True, blank=True)
    executado_em  = models.DateTimeField(null=True, blank=True)
    pendente_em   = models.DateTimeField(null=True, blank=True)   # NOVO
    finalizado_em = models.DateTimeField(null=True, blank=True)

    # ------------------------------------------------------------------
    # Soft delete
    # ------------------------------------------------------------------
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="gestao_tarefas_deletadas",
    )

    objects     = TarefaManager()
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

    # ------------------------------------------------------------------
    # Geração automática do código
    # ------------------------------------------------------------------
    def save(self, *args, **kwargs):
        # Só gera na criação (pk ainda não existe)
        _update_fields = kwargs.get("update_fields")
        if not self.pk and not self.codigo:
            # Salva primeiro para obter o pk
            super().save(*args, **kwargs)
            self.codigo = f"GES-{self.pk:05d}"
            self.save(update_fields=["codigo"])
            return
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Propriedades de tempo
    # ------------------------------------------------------------------
    @property
    def esta_atrasada(self):
        if self.status not in {self.Status.ABERTA, self.Status.EXECUTANDO, self.Status.PENDENTE}:
            return False
        return timezone.now() > self.prazo

    @property
    def vencendo(self):
        if self.status not in {self.Status.ABERTA, self.Status.EXECUTANDO, self.Status.PENDENTE}:
            return False
        agora = timezone.now()
        return agora <= self.prazo <= (agora + timezone.timedelta(hours=6))

    # ------------------------------------------------------------------
    # Transições de status
    # ------------------------------------------------------------------
    def iniciar_execucao(self, user=None):
        self.status = self.Status.EXECUTANDO
        if user and not self.executor:
            self.executor = user
        if not self.iniciado_em:
            self.iniciado_em = timezone.now()
        self.executado_em = None
        self.pendente_em  = None
        self.finalizado_em = None

    def marcar_executado(self):
        self.status = self.Status.EXECUTADO
        if not self.executado_em:
            self.executado_em = timezone.now()
        self.pendente_em  = None
        self.finalizado_em = None

    def marcar_pendente(self):
        """
        Criador validou e devolveu: executor precisa refazer.
        Card sai da coluna EXECUTADO e vai para PENDENTE na tela do criador
        (dourado), e ao devolver volta para EXECUTANDO (laranja) para o executor.
        """
        self.status = self.Status.PENDENTE
        if not self.pendente_em:
            self.pendente_em = timezone.now()
        self.finalizado_em = None

    def devolver_execucao(self):
        """Card PENDENTE volta para EXECUTANDO para o executor refazer."""
        self.status = self.Status.EXECUTANDO
        # Mantém iniciado_em e executor originais
        self.executado_em  = None
        self.pendente_em   = None
        self.finalizado_em = None

    def finalizar(self):
        self.status = self.Status.FEITA
        if not self.finalizado_em:
            self.finalizado_em = timezone.now()

    def reabrir(self):
        self.status = self.Status.ABERTA
        self.iniciado_em   = None
        self.executado_em  = None
        self.pendente_em   = None
        self.finalizado_em = None
        self.executor      = None


class Anexo(models.Model):
    tarefa       = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="anexos")
    arquivo      = models.FileField(upload_to="gestao/anexos/")
    nome_original = models.CharField(max_length=255, blank=True)
    enviado_por  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    enviado_em = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.arquivo and not self.nome_original:
            self.nome_original = self.arquivo.name.split("/")[-1].split("\\")[-1]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Anexo({self.nome_original}) - tarefa {self.tarefa_id}"


class Comentario(models.Model):
    tarefa    = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="comentarios")
    autor     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    texto     = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    # Sinaliza comentários de devolução para destaque visual no histórico
    eh_devolucao = models.BooleanField(default=False)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Comentario({self.id}) tarefa {self.tarefa_id}"
