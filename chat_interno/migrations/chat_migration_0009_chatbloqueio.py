from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chat_interno", "0008_chatvinculooperador_multi_supervisor"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatBloqueio",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "motivo",
                    models.CharField(
                        blank=True,
                        help_text="Registro interno — não exibido aos usuários.",
                        max_length=255,
                        verbose_name="Motivo (opcional)",
                    ),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "user_a",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_bloqueios_como_a",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuário A",
                    ),
                ),
                (
                    "user_b",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_bloqueios_como_b",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuário B",
                    ),
                ),
            ],
            options={
                "verbose_name": "Bloqueio de chat entre usuários",
                "verbose_name_plural": "Bloqueios de chat entre usuários",
                "ordering": ["user_a__username", "user_b__username"],
            },
        ),
        migrations.AddConstraint(
            model_name="chatbloqueio",
            constraint=models.UniqueConstraint(
                fields=["user_a", "user_b"],
                name="uniq_chat_bloqueio_par",
            ),
        ),
    ]
