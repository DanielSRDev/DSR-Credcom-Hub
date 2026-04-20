from django.db import models


class SupervisorPainel(models.Model):
    nome = models.CharField("Nome", max_length=150, unique=True)
    ativo = models.BooleanField("Ativo", default=True)
    ordem = models.PositiveIntegerField("Ordem", default=0)
    meta_diaria = models.DecimalField("Meta diária", max_digits=12, decimal_places=2, default=0)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Supervisor do Painel"
        verbose_name_plural = "Supervisores do Painel"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class CarteiraSupervisor(models.Model):
    supervisor = models.ForeignKey(
        SupervisorPainel,
        on_delete=models.CASCADE,
        related_name="carteiras"
    )
    cre_id = models.BigIntegerField("ID do Credor", unique=True)
    credor_nome = models.CharField("Nome do Credor", max_length=255)
    ativo = models.BooleanField("Ativo", default=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Carteira por Supervisor"
        verbose_name_plural = "Carteiras por Supervisor"
        ordering = ["credor_nome"]

    def __str__(self):
        return f"{self.credor_nome} -> {self.supervisor.nome}"


class OperadorAlias(models.Model):
    login_original = models.CharField("Login original", max_length=255, unique=True)
    nome_exibicao = models.CharField("Nome correto", max_length=255)
    ativo = models.BooleanField("Ativo", default=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Alias de Operador"
        verbose_name_plural = "Aliases de Operadores"
        ordering = ["nome_exibicao"]

    def __str__(self):
        return f"{self.login_original} -> {self.nome_exibicao}"


class PainelConfiguracao(models.Model):
    meta_mensal_geral = models.DecimalField("Meta mensal geral", max_digits=14, decimal_places=2, default=0)
    meta_diaria_geral = models.DecimalField("Meta diária geral", max_digits=14, decimal_places=2, default=0)
    intervalo_horas_sync = models.PositiveIntegerField("Intervalo sync (horas)", default=3)
    ativo = models.BooleanField("Ativo", default=True)
    ultima_atualizacao = models.DateTimeField("Última atualização", null=True, blank=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Configuração do Painel"
        verbose_name_plural = "Configurações do Painel"

    def __str__(self):
        return "Configuração Geral do Painel"


class PainelSyncLog(models.Model):
    iniciado_em = models.DateTimeField("Iniciado em", auto_now_add=True)
    finalizado_em = models.DateTimeField("Finalizado em", null=True, blank=True)
    sucesso = models.BooleanField("Sucesso", default=False)
    total_registros = models.PositiveIntegerField("Total de registros", default=0)
    mensagem = models.TextField("Mensagem", blank=True, default="")

    class Meta:
        verbose_name = "Log de Sincronização"
        verbose_name_plural = "Logs de Sincronização"
        ordering = ["-iniciado_em"]

    def __str__(self):
        return f"Sync {self.iniciado_em:%d/%m/%Y %H:%M}"


class PainelOperacaoRegistro(models.Model):
    data_referencia = models.DateField("Data de referência", null=True, blank=True)
    data_acordo = models.DateTimeField("Data do acordo", null=True, blank=True)
    data_emissao = models.DateTimeField("Data da emissão", null=True, blank=True)
    data_etl_alteracao = models.DateTimeField("Data ETL alteração", null=True, blank=True)

    numero_acordo = models.CharField("Número do acordo", max_length=100, blank=True, default="")
    aco_id = models.BigIntegerField("Aco ID", db_index=True)
    contrato = models.CharField("Contrato", max_length=100, blank=True, default="")

    cliente = models.CharField("Cliente", max_length=255, blank=True, default="")
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=30, blank=True, default="")

    cre_id = models.BigIntegerField("Credor ID", null=True, blank=True, db_index=True)
    credor = models.CharField("Credor", max_length=255, blank=True, default="")
    filial = models.CharField("Filial", max_length=255, blank=True, default="")
    tipo_contrato = models.CharField("Tipo contrato", max_length=255, blank=True, default="")
    tipo_negociacao = models.CharField("Tipo negociação", max_length=500, blank=True, default="")

    principal_bruto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    desconto_principal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    principal_liquido = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    multa_bruta = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    desconto_multa = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    multa_liquida = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    juros_bruto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    desconto_juros = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    juros_liquido = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    honorario_bruto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    desconto_honorario = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    honorario_liquido = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    despesas = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    subtotal_bruto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    desconto_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valor_total_liquido = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valor_entrada = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    qtd_parcelas_acordo = models.IntegerField(default=0)
    status_acordo = models.CharField(max_length=255, blank=True, default="")
    tipo_acordo = models.CharField(max_length=255, blank=True, default="")

    emitido_por_login = models.CharField("Emitido por login", max_length=255, blank=True, default="", db_index=True)
    emitido_por_nome = models.CharField("Emitido por nome", max_length=255, blank=True, default="", db_index=True)
    supervisor_nome = models.CharField("Supervisor", max_length=150, blank=True, default="", db_index=True)

    valor_emissao = models.DecimalField("Emissao", max_digits=14, decimal_places=2, default=0)
    valor_pago = models.DecimalField("Pago", max_digits=14, decimal_places=2, default=0)
    valor_avencer = models.DecimalField("Avencer", max_digits=14, decimal_places=2, default=0)
    valor_quebra = models.DecimalField("Quebra", max_digits=14, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Registro do Painel Operação"
        verbose_name_plural = "Registros do Painel Operação"
        ordering = ["-data_emissao", "-aco_id"]
        indexes = [
            models.Index(fields=["data_emissao"]),
            models.Index(fields=["credor"]),
            models.Index(fields=["supervisor_nome"]),
            models.Index(fields=["emitido_por_nome"]),
        ]

    def __str__(self):
        return f"{self.numero_acordo} - {self.cliente}"