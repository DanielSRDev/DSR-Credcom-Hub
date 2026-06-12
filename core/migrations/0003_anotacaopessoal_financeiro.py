from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_perfilusuario"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AnotacaoPessoal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("texto", models.TextField(verbose_name="Anotação")),
                ("concluida", models.BooleanField(default=False, verbose_name="Concluída")),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="anotacoes_pessoais",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuário",
                    ),
                ),
            ],
            options={
                "verbose_name": "Anotação pessoal",
                "verbose_name_plural": "Anotações pessoais",
                "ordering": ["concluida", "-criado_em"],
            },
        ),
        migrations.AlterField(
            model_name="usuariorestricaomodulo",
            name="modulo_bloqueado",
            field=models.CharField(
                choices=[
                    ("nibo", "Nibo Panel"),
                    ("gestao", "Gestão"),
                    ("operacao", "Operação"),
                    ("zapmsg", "ZapMsg (WhatsApp)"),
                    ("painel_operacao", "Painel Operação"),
                    ("chat", "Chat Interno"),
                    ("financeiro", "Financeiro"),
                ],
                max_length=30,
                verbose_name="Módulo bloqueado",
            ),
        ),
    ]
