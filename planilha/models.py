from django.conf import settings
from django.db import models


class PlanilhaImportacao(models.Model):
    """
    Base ATUAL de uma carteira (um registro por cre_id / Codigo).

    Na reimportação de um mesmo cre_id, a base antiga é exportada em Excel
    (devolvida ao importador) e apagada; este registro passa a apontar para a
    importação nova.
    """
    cre_id = models.BigIntegerField("Código (cre_id)", unique=True, db_index=True)
    carteira_nome = models.CharField("Carteira", max_length=255)

    arquivo_nome = models.CharField("Arquivo importado", max_length=255, blank=True, default="")
    importado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="planilha_importacoes",
        verbose_name="Importado por",
    )
    total_contratos = models.PositiveIntegerField("Total de contratos", default=0)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Importação de Planilha"
        verbose_name_plural = "Importações de Planilha"
        ordering = ["carteira_nome"]

    def __str__(self):
        return f"{self.carteira_nome} ({self.cre_id})"


class PlanilhaImportLog(models.Model):
    """Auditoria de cada importação — inclusive a substituição (reimportação)."""
    cre_id = models.BigIntegerField("Código (cre_id)", db_index=True)
    carteira_nome = models.CharField("Carteira", max_length=255, blank=True, default="")
    importado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="planilha_import_logs",
        verbose_name="Importado por",
    )
    total_inseridos = models.PositiveIntegerField("Contratos inseridos", default=0)
    total_removidos = models.PositiveIntegerField("Contratos removidos (base antiga)", default=0)
    inconsistencias = models.PositiveIntegerField("Inconsistências", default=0)
    importado_mesmo_com_erros = models.BooleanField(default=False)
    arquivo_devolvido = models.CharField(
        "Excel da base antiga devolvido", max_length=255, blank=True, default=""
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log de Importação"
        verbose_name_plural = "Logs de Importação"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.carteira_nome} ({self.cre_id}) — {self.criado_em:%d/%m/%Y %H:%M}"


class PlanilhaContrato(models.Model):
    """
    Uma linha da base = um contrato. O CPF pode se repetir em vários contratos,
    mas cada CPF deve ter um único operador responsável (validado na importação).
    """
    importacao = models.ForeignKey(
        PlanilhaImportacao,
        on_delete=models.CASCADE,
        related_name="contratos",
        verbose_name="Importação",
    )

    # --- campos vindos da planilha (aba 'Operador') ---
    cre_id = models.BigIntegerField("Código (cre_id)", db_index=True)
    carteira_nome = models.CharField("Carteira", max_length=255, db_index=True)
    operador_nome = models.CharField("Operador", max_length=255, db_index=True)
    nr_contrato = models.CharField("Nr Contrato", max_length=100, db_index=True)
    tipo_contrato = models.CharField("Tipo do Contrato", max_length=255, blank=True, default="")
    empreendimento = models.CharField("Empreendimento", max_length=255, blank=True, default="", db_index=True)
    atraso_real = models.IntegerField("Atraso real (dias)", null=True, blank=True, db_index=True)
    vlr_total = models.DecimalField("Vlr total", max_digits=14, decimal_places=2, default=0, db_index=True)
    status_antigo = models.CharField("Status Antigo", max_length=100, blank=True, default="")
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=30, blank=True, default="", db_index=True)
    nome_cliente = models.CharField("Nome", max_length=255, blank=True, default="", db_index=True)

    # Colunas extras (só algumas bases trazem — ex.: CodEmpresa/CodObra).
    # Guardadas pra sair na exportação/devolução, mas não aparecem na tela.
    cod_empresa = models.CharField("Cód. Empresa", max_length=50, blank=True, default="")
    cod_obra = models.CharField("Cód. Obra", max_length=50, blank=True, default="")

    # Preenchido via sincronização com o banco Virtua (EVENTOSCOBRANCA), casando
    # nr_contrato = NROPERACAO. status_atual_data = DATAHORA do último evento.
    status_atual = models.CharField("Status Atual", max_length=150, blank=True, default="")
    status_atual_data = models.DateTimeField("Data do Status Atual", null=True, blank=True)

    # --- marcações no HUB ---
    prioridade = models.BooleanField("Prioridade", default=False, db_index=True)
    prioridade_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="planilha_prioridades",
        verbose_name="Prioridade marcada por",
    )
    prioridade_em = models.DateTimeField(null=True, blank=True)

    # Destaque = uma cor (vazio = sem destaque).
    destaque_cor = models.CharField("Cor de destaque", max_length=20, blank=True, default="")

    # Fila ordenada montada pelo supervisor (posição 1,2,3…; vazio = fora da fila).
    fila_ordem = models.IntegerField("Ordem na fila", null=True, blank=True, db_index=True)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Contrato da Planilha"
        verbose_name_plural = "Contratos da Planilha"
        ordering = ["-prioridade", "-atraso_real", "nome_cliente"]
        indexes = [
            models.Index(fields=["cre_id", "operador_nome"]),
            models.Index(fields=["cre_id", "cpf_cnpj"]),
        ]

    def __str__(self):
        return f"{self.nr_contrato} — {self.nome_cliente} ({self.operador_nome})"

    @property
    def dias_status_atual(self):
        """Dias corridos desde o último evento de cobrança (Virtua), ou None se nunca houve."""
        if not self.status_atual_data:
            return None
        from django.utils import timezone
        return (timezone.now() - self.status_atual_data).days


class PlanilhaCompartilhamento(models.Model):
    """
    Concede a `usuario` acesso à base de cada um dos `colegas` (além da
    própria), sem depender de Equipe/CarteiraSupervisor. Gerenciado só pelo
    Django Admin. Para acesso mútuo entre duas pessoas, criar um registro
    para cada lado (A→colega B, e B→colega A).
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="planilha_compartilhamentos",
        verbose_name="Usuário (ganha acesso extra)",
    )
    colegas = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="planilha_compartilhado_com",
        verbose_name="Também pode ver a base de",
        blank=True,
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Compartilhamento de Base (Planilha)"
        verbose_name_plural = "Compartilhamentos de Base (Planilha)"

    def __str__(self):
        return f"{self.usuario} vê também: {', '.join(str(c) for c in self.colegas.all())}"


class PlanilhaAcrescimo(models.Model):
    """Dado adicional que o operador acrescenta a um contrato (telefone/email/nota)."""

    class Tipo(models.TextChoices):
        TELEFONE = "telefone", "Telefone"
        EMAIL = "email", "E-mail"
        NOTA = "nota", "Nota / Lembrete"

    contrato = models.ForeignKey(
        PlanilhaContrato,
        on_delete=models.CASCADE,
        related_name="acrescimos",
        verbose_name="Contrato",
    )
    tipo = models.CharField("Tipo", max_length=20, choices=Tipo.choices)
    valor = models.TextField("Valor")
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="planilha_acrescimos",
        verbose_name="Criado por",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Acréscimo ao Contrato"
        verbose_name_plural = "Acréscimos aos Contratos"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.contrato_id}"


class PlanilhaStatusAcionamento(models.Model):
    """Lista de status de acionamento, gerenciada no admin (ex.: 'Promessa de pagamento')."""
    nome = models.CharField("Status", max_length=100, unique=True)
    ordem = models.PositiveIntegerField("Ordem", default=0)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Status de Acionamento"
        verbose_name_plural = "Status de Acionamento"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class PlanilhaAcionamento(models.Model):
    """Histórico de acionamento de um contrato: status escolhido + comentário do operador."""
    contrato = models.ForeignKey(
        PlanilhaContrato,
        on_delete=models.CASCADE,
        related_name="acionamentos",
        verbose_name="Contrato",
    )
    status = models.ForeignKey(
        PlanilhaStatusAcionamento,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="acionamentos",
        verbose_name="Status",
    )
    comentario = models.TextField("Comentário", blank=True, default="")
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="planilha_acionamentos",
        verbose_name="Registrado por",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Acionamento"
        verbose_name_plural = "Acionamentos (histórico)"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.contrato_id} — {self.status or 'sem status'}"
