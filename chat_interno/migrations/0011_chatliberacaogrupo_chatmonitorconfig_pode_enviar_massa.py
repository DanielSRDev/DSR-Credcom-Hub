import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat_interno", "0010_message_reply_to_messagereaction"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmonitorconfig",
            name="pode_enviar_massa",
            field=models.BooleanField(default=False, verbose_name="Pode enviar mensagem em massa"),
        ),
        migrations.CreateModel(
            name="ChatLiberacaoGrupo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("para_todos", models.BooleanField(default=False, verbose_name="Liberar para todos os usuários ativos")),
                ("motivo", models.CharField(blank=True, max_length=255, verbose_name="Motivo (opcional)")),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_liberacoes_grupo",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuário central",
                    ),
                ),
                (
                    "membros",
                    models.ManyToManyField(
                        blank=True,
                        related_name="chat_liberacoes_grupo_membro",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Membros do grupão",
                    ),
                ),
            ],
            options={
                "verbose_name": "Liberação de chat em grupo (grupão)",
                "verbose_name_plural": "Liberações de chat em grupo (grupão)",
                "ordering": ["usuario__username"],
            },
        ),
    ]
