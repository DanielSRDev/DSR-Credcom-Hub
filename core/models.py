import logging

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger("core.models")


class ConfiguracaoSeguranca(models.Model):
    """
    Configuração única (singleton) compartilhada pelos módulos Operação e Gestão.

    - senha_reabertura: hash da senha exigida para reabrir um card finalizado.
      Reabrir não depende mais de grupo — qualquer pessoa que veja o card e
      saiba esta senha pode reabri-lo.
    - prazo_validacao_dias: prazo (em dias) que o validador tem, a partir de
      `executado_em`, para validar um card EXECUTADO. Esgotado o prazo, o card
      é finalizado automaticamente.
    """

    senha_reabertura = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Senha de reabertura (hash)",
        help_text="Não editar aqui — defina pela caixa 'Nova senha' no formulário.",
    )
    prazo_validacao_dias = models.PositiveIntegerField(
        default=2,
        verbose_name="Prazo de validação (dias)",
        help_text="Dias para validar um card EXECUTADO antes de finalizar automaticamente.",
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração de Segurança"
        verbose_name_plural = "Configuração de Segurança"

    def __str__(self):
        return "Configuração de Segurança"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def set_senha(self, raw: str):
        self.senha_reabertura = make_password(raw)

    def check_senha(self, raw: str) -> bool:
        if not self.senha_reabertura or not raw:
            return False
        return check_password(raw, self.senha_reabertura)


class PerfilUsuario(models.Model):
    """
    Perfil estendido do usuário.

    deve_trocar_senha = True  → usuário será redirecionado para criar
                                nova senha assim que fizer login.
    Admin pode marcar novamente para forçar troca (ex.: reset de senha).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil",
        verbose_name="Usuário",
    )
    deve_trocar_senha = models.BooleanField(
        default=True,
        verbose_name="Deve trocar senha no próximo acesso",
        help_text="Marque para forçar o usuário a criar nova senha no próximo login.",
    )
    pode_publicar_jornal = models.BooleanField(
        default=False,
        verbose_name="Pode publicar no Jornal",
        help_text="Marque para permitir que este usuário publique novidades no Jornal.",
    )

    class Meta:
        verbose_name = "Perfil de usuário"
        verbose_name_plural = "Perfis de usuários"

    def __str__(self):
        return f"Perfil de {self.user.username}"


@receiver(pre_save, sender=settings.AUTH_USER_MODEL)
def marcar_senha_mudou(sender, instance, **kwargs):
    """
    Antes de salvar o usuário, detecta se a senha mudou.
    Seta instance._senha_mudou = True para uso no post_save.
    Ignorado quando _skip_primeiro_acesso=True (evita loop na view primeiro_acesso).
    """
    if not instance.pk:
        return  # novo usuário — tratado por criar_perfil_usuario
    if getattr(instance, "_skip_primeiro_acesso", False):
        return  # suprimido pela view primeiro_acesso
    try:
        antigo = sender.objects.get(pk=instance.pk)
        if antigo.password != instance.password:
            instance._senha_mudou = True
    except sender.DoesNotExist:
        pass


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_perfil_usuario(sender, instance, created, **kwargs):
    """
    Cria o perfil automaticamente quando um novo usuário é criado.
    Se a senha mudou num usuário existente, força deve_trocar_senha = True.
    """
    if created:
        PerfilUsuario.objects.get_or_create(user=instance)
    elif getattr(instance, "_senha_mudou", False):
        try:
            perfil, _ = PerfilUsuario.objects.get_or_create(user=instance)
            perfil.deve_trocar_senha = True
            perfil.save(update_fields=["deve_trocar_senha"])
        except Exception:
            logger.exception(
                "Erro ao setar deve_trocar_senha via signal para user pk=%s", instance.pk
            )


class AnotacaoPessoal(models.Model):
    """
    Bloco de notas pessoal do usuário — lembretes, acessos, recados etc.
    Visível e editável apenas pelo próprio usuário.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="anotacoes_pessoais",
        verbose_name="Usuário",
    )
    class Cor(models.TextChoices):
        PADRAO  = "padrao",  "Padrão"
        AMARELO = "amarelo", "Amarelo"
        VERDE   = "verde",   "Verde"
        AZUL    = "azul",    "Azul"
        ROSA    = "rosa",    "Rosa"
        VERMELHO = "vermelho", "Vermelho"

    texto = models.TextField(verbose_name="Anotação")
    concluida = models.BooleanField(default=False, verbose_name="Concluída")
    fixada = models.BooleanField(default=False, verbose_name="Fixada")
    cor = models.CharField(max_length=10, choices=Cor.choices, default=Cor.PADRAO, verbose_name="Cor")
    lembrete_em = models.DateTimeField(null=True, blank=True, verbose_name="Lembrar em")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Anotação pessoal"
        verbose_name_plural = "Anotações pessoais"
        ordering = ["concluida", "-fixada", "-criado_em"]

    def __str__(self):
        return f"{self.user.username}: {self.texto[:40]}"


class JornalPost(models.Model):
    """
    Postagem do "Jornal" (mural de novidades/atualizações) exibido na navbar.
    """

    ARQUIVO_EXTS = ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "txt", "csv"]

    titulo = models.CharField(max_length=200, verbose_name="Título")
    conteudo = models.TextField(verbose_name="Conteúdo")
    imagem = models.ImageField(upload_to="jornal/", blank=True, null=True, verbose_name="Imagem")
    arquivo = models.FileField(
        upload_to="jornal/arquivos/",
        blank=True,
        null=True,
        verbose_name="Arquivo (PDF, DOC, etc.)",
        validators=[FileExtensionValidator(allowed_extensions=ARQUIVO_EXTS)],
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="jornal_posts",
        verbose_name="Autor",
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Publicado em")
    editado_em = models.DateTimeField(null=True, blank=True, verbose_name="Editado em")

    class Meta:
        verbose_name = "Postagem do Jornal"
        verbose_name_plural = "Postagens do Jornal"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.titulo

    @property
    def nome_arquivo(self):
        if not self.arquivo:
            return ""
        return self.arquivo.name.rsplit("/", 1)[-1]


class JornalComentario(models.Model):
    """
    Comentário de um usuário em uma postagem do Jornal.
    """

    post = models.ForeignKey(
        JornalPost,
        on_delete=models.CASCADE,
        related_name="comentarios",
        verbose_name="Postagem",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jornal_comentarios",
        verbose_name="Usuário",
    )
    texto = models.TextField(verbose_name="Comentário")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Comentado em")

    class Meta:
        verbose_name = "Comentário do Jornal"
        verbose_name_plural = "Comentários do Jornal"
        ordering = ["criado_em"]

    def __str__(self):
        return f"{self.user.username} comentou #{self.post_id}"


class JornalReacao(models.Model):
    """
    Reação (emoji) de um usuário a uma postagem OU a um comentário do Jornal.

    Exatamente um entre ``post`` e ``comentario`` é preenchido. Um usuário pode
    ter, no mesmo alvo, no máximo uma reação por emoji (mas pode usar emojis
    diferentes no mesmo alvo — estilo Slack).
    """

    # Paleta de reações disponíveis (ordem usada no seletor da interface).
    EMOJIS = ["👍", "❤️", "😂", "🔥", "😮", "👏", "🎉", "😢"]

    post = models.ForeignKey(
        JornalPost,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reacoes",
        verbose_name="Postagem",
    )
    comentario = models.ForeignKey(
        JornalComentario,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reacoes",
        verbose_name="Comentário",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jornal_reacoes",
        verbose_name="Usuário",
    )
    emoji = models.CharField(max_length=8, verbose_name="Reação")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Reação do Jornal"
        verbose_name_plural = "Reações do Jornal"
        constraints = [
            # NULLs são distintos no Postgres, então cada constraint só atua
            # sobre o alvo correspondente — juntas garantem unicidade por alvo.
            models.UniqueConstraint(
                fields=["post", "user", "emoji"], name="uniq_reacao_post"
            ),
            models.UniqueConstraint(
                fields=["comentario", "user", "emoji"], name="uniq_reacao_comentario"
            ),
        ]

    def __str__(self):
        alvo = f"post #{self.post_id}" if self.post_id else f"comentário #{self.comentario_id}"
        return f"{self.user_id} reagiu {self.emoji} em {alvo}"


class JornalLeitura(models.Model):
    """
    Guarda a última postagem do Jornal já vista por cada usuário,
    para exibir o aviso de novidade apenas uma vez por post.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jornal_leitura",
        verbose_name="Usuário",
    )
    ultimo_post_visto = models.ForeignKey(
        JornalPost,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Última postagem vista",
    )

    class Meta:
        verbose_name = "Leitura do Jornal"
        verbose_name_plural = "Leituras do Jornal"

    def __str__(self):
        return f"{self.user.username} — visto até #{self.ultimo_post_visto_id}"


class UsuarioRestricaoModulo(models.Model):
    """
    Blacklist de módulos por usuário.

    Mesmo que o usuário tenha o grupo que daria acesso ao módulo,
    se existir um registro aqui com modulo_bloqueado correspondente,
    o middleware negará o acesso e o context_processor ocultará o item
    da navbar.

    Superuser nunca é bloqueado — a checagem no middleware e no
    context_processor pula superusers explicitamente.
    """

    class Modulo(models.TextChoices):
        NIBO            = "nibo",            "Nibo Panel"
        GESTAO          = "gestao",          "Gestão"
        OPERACAO        = "operacao",        "Operação"
        ZAPMSG          = "zapmsg",          "ZapMsg (WhatsApp)"
        PAINEL_OPERACAO = "painel_operacao", "Painel Operação"
        CHAT            = "chat",            "Chat Interno"
        FINANCEIRO      = "financeiro",      "Financeiro"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="restricoes_modulo",
        verbose_name="Usuário",
    )
    modulo_bloqueado = models.CharField(
        max_length=30,
        choices=Modulo.choices,
        verbose_name="Módulo bloqueado",
    )
    motivo = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Motivo (opcional)",
        help_text="Registro interno — não exibido ao usuário.",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Restrição de módulo por usuário"
        verbose_name_plural = "Restrições de módulo por usuário"
        unique_together = ("user", "modulo_bloqueado")
        ordering = ["user__username", "modulo_bloqueado"]

    def __str__(self):
        return f"{self.user.username} — bloqueado: {self.get_modulo_bloqueado_display()}"