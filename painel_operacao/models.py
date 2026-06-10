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


class MetaOperadorCarteira(models.Model):
    """Meta mensal individual por operador e carteira.

    Regra: a Meta Geral do Acompanhamento é a soma das metas ativas
    cadastradas para o mês/ano filtrado.
    """
    ano = models.PositiveIntegerField("Ano", db_index=True)
    mes = models.PositiveSmallIntegerField("Mês", db_index=True)

    carteira = models.ForeignKey(
        CarteiraSupervisor,
        on_delete=models.CASCADE,
        related_name="metas_operadores",
        verbose_name="Carteira",
    )

    operador_login = models.CharField("Login do operador", max_length=255, blank=True, default="", db_index=True)
    operador_nome = models.CharField("Nome do operador", max_length=255, db_index=True)

    meta_mensal = models.DecimalField("Meta mensal", max_digits=14, decimal_places=2, default=0)
    ativo = models.BooleanField("Ativo", default=True)

    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Meta por Operador e Carteira"
        verbose_name_plural = "Metas por Operador e Carteira"
        ordering = ["-ano", "-mes", "carteira__credor_nome", "operador_nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["ano", "mes", "carteira", "operador_login", "operador_nome"],
                name="uniq_meta_operador_carteira_mes",
            )
        ]
        indexes = [
            models.Index(fields=["ano", "mes", "ativo"]),
            models.Index(fields=["operador_nome"]),
            models.Index(fields=["operador_login"]),
        ]

    def __str__(self):
        login = f" ({self.operador_login})" if self.operador_login else ""
        return f"{self.mes:02d}/{self.ano} - {self.operador_nome}{login} - {self.carteira.credor_nome}: R$ {self.meta_mensal}"


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
    dias_uteis_mes = models.PositiveSmallIntegerField(
        "Dias úteis do mês vigente",
        default=22,
        help_text="Informe a quantidade de dias úteis do mês atual. O sistema calcula os dias faltantes automaticamente.",
    )
    sync_data_ini = models.DateField(
        "Data inicial do sync",
        null=True,
        blank=True,
        help_text="Início do período usado pelo botão 'Atualizar dados'. Deixe em branco para usar o 1º dia do mês atual.",
    )
    sync_data_fim = models.DateField(
        "Data final do sync",
        null=True,
        blank=True,
        help_text="Fim do período usado pelo botão 'Atualizar dados'. Deixe em branco para usar a data de hoje.",
    )
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
    tipo_sync = models.CharField("Tipo sync", max_length=30, default="PAINEL")

    class Meta:
        verbose_name = "Log de Sincronização"
        verbose_name_plural = "Logs de Sincronização"
        ordering = ["-iniciado_em"]

    def __str__(self):
        return f"{self.tipo_sync} - {self.iniciado_em:%d/%m/%Y %H:%M}"


class PainelOperacaoPagamento(models.Model):
    pgo_id = models.BigIntegerField("Pagamento ID", unique=True, db_index=True)
    aco_id = models.BigIntegerField("Acordo ID", db_index=True)
    pct_id = models.BigIntegerField("PCT ID", null=True, blank=True, db_index=True)
    pgo_data = models.DateTimeField("Data pagamento", null=True, blank=True)
    pgo_valor = models.DecimalField("Valor pagamento", max_digits=14, decimal_places=2, default=0)
    fpg_id = models.IntegerField("Forma pagamento ID", null=True, blank=True)
    pgo_parcial = models.BooleanField("Pagamento parcial", default=False)
    pgo_etl_alteracao = models.DateTimeField("ETL alteração", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pagamento do Painel Operação"
        verbose_name_plural = "Pagamentos do Painel Operação"
        ordering = ["-pgo_data", "-pgo_id"]
        indexes = [
            models.Index(fields=["aco_id"]),
            models.Index(fields=["pgo_data"]),
        ]

    def __str__(self):
        return f"{self.pgo_id} -> {self.aco_id}"


class PainelOperacaoRegistro(models.Model):
    data_referencia = models.DateField("Data de referência", null=True, blank=True)
    data_acordo = models.DateTimeField("Data do acordo", null=True, blank=True)
    data_emissao = models.DateTimeField("Data da emissão", null=True, blank=True)
    data_etl_alteracao = models.DateTimeField("Data ETL alteração", null=True, blank=True)

    numero_acordo = models.CharField("Número do acordo", max_length=100, blank=True, default="")
    aco_id = models.BigIntegerField("Aco ID", db_index=True)
    contrato = models.CharField("Contrato", max_length=100, blank=True, default="")
    con_id = models.BigIntegerField("Contrato ID", null=True, blank=True, db_index=True)
    observacao_contrato = models.TextField("Observação do contrato", blank=True, null=True)

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
    despesa_liquida = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    taxa_liquida = models.DecimalField(max_digits=14, decimal_places=2, default=0)
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

    tem_pagamento = models.BooleanField("Tem pagamento", default=False)

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
            models.Index(fields=["aco_id"]),
        ]

    def __str__(self):
        return f"{self.numero_acordo} - {self.cliente}"


class PainelOperacaoRelatorioGeral(models.Model):
    origem_registro = models.CharField("Origem", max_length=30, db_index=True)

    data_referencia = models.DateField("Data de referência", null=True, blank=True)
    data_acordo = models.DateTimeField("Data do acordo", null=True, blank=True)
    data_emissao = models.DateTimeField("Data da emissão", null=True, blank=True)
    data_pagamento = models.DateTimeField("Data do pagamento", null=True, blank=True)
    data_etl_alteracao = models.DateTimeField("Data ETL alteração", null=True, blank=True)

    numero_acordo = models.CharField("Número do acordo", max_length=100, blank=True, default="")
    aco_id = models.BigIntegerField("Aco ID", db_index=True)
    contrato = models.CharField("Contrato", max_length=100, blank=True, default="")
    con_id = models.BigIntegerField("Contrato ID", null=True, blank=True, db_index=True)
    observacao_contrato = models.TextField(blank=True, null=True)

    cliente = models.CharField("Cliente", max_length=255, blank=True, default="")
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=30, blank=True, default="")

    cre_id = models.BigIntegerField("Credor ID", null=True, blank=True, db_index=True)
    credor = models.CharField("Credor", max_length=255, blank=True, default="")
    filial = models.CharField("Filial", max_length=255, blank=True, default="")
    tipo_contrato = models.CharField("Tipo contrato", max_length=255, blank=True, default="")
    tipo_negociacao = models.CharField("Tipo negociação", max_length=500, blank=True, default="")

    honorario_bruto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    desconto_honorario = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    honorario_liquido = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Campos usados somente para enriquecer a exportação da Planilha Geral.
    # Não entram na regra financeira do HUB; a regra do painel continua usando honorário líquido.
    principal_liquido = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    multa_liquida = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    juros_liquido = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valor_parcela = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valor_total_acordo = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    despesas = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    despesa_liquida = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    taxa_liquida = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valor_entrada = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valor_pagamento_periodo = models.DecimalField(max_digits=14, decimal_places=2, default=0)

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
        verbose_name = "Relatório Geral do Painel"
        verbose_name_plural = "Relatórios Gerais do Painel"
        ordering = ["-data_referencia", "-data_pagamento", "-data_emissao", "-aco_id"]
        indexes = [
            models.Index(fields=["origem_registro"]),
            models.Index(fields=["data_referencia"]),
            models.Index(fields=["data_pagamento"]),
            models.Index(fields=["data_emissao"]),
            models.Index(fields=["aco_id"]),
            models.Index(fields=["emitido_por_nome"]),
        ]

    def __str__(self):
        return f"{self.origem_registro} - {self.numero_acordo} - {self.cliente}"