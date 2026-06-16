import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0006_perfilusuario_pode_publicar_jornal"),
    ]

    operations = [
        migrations.AddField(
            model_name="jornalpost",
            name="arquivo",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="jornal/arquivos/",
                verbose_name="Arquivo (PDF, DOC, etc.)",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "txt", "csv"]
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="jornalpost",
            name="editado_em",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Editado em"),
        ),
        migrations.CreateModel(
            name="JornalLike",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("post", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="likes", to="core.jornalpost", verbose_name="Postagem")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="jornal_likes", to=settings.AUTH_USER_MODEL, verbose_name="Usuário")),
            ],
            options={
                "verbose_name": "Curtida do Jornal",
                "verbose_name_plural": "Curtidas do Jornal",
                "unique_together": {("post", "user")},
            },
        ),
    ]
