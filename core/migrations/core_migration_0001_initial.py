from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UsuarioRestricaoModulo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "modulo_bloqueado",
                    models.CharField(
                        choices=[
                            ("nibo", "Nibo Panel"),
                            ("gestao", "Gestão"),
                            ("operacao", "Operação"),
                            ("zapmsg", "ZapMsg (WhatsApp)"),
                            ("painel_operacao", "Painel Operação"),
                            ("chat", "Chat Interno"),
                        ],
                        max_length=30,
                        verbose_name="Módulo bloqueado",
                    ),
                ),
                (
                    "motivo",
                    models.CharField(
                        blank=True,
                        help_text="Registro interno — não exibido ao usuário.",
                        max_length=255,
                        verbose_name="Motivo (opcional)",
                    ),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="restricoes_modulo",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuário",
                    ),
                ),
            ],
            options={
                "verbose_name": "Restrição de módulo por usuário",
                "verbose_name_plural": "Restrições de módulo por usuário",
                "ordering": ["user__username", "modulo_bloqueado"],
            },
        ),
        migrations.AlterUniqueTogether(
            name="usuariorestricaomodulo",
            unique_together={("user", "modulo_bloqueado")},
        ),
    ]
