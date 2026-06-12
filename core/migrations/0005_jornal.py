import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0004_anotacaopessoal_cor_fixada_lembrete"),
    ]

    operations = [
        migrations.CreateModel(
            name="JornalPost",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("titulo", models.CharField(max_length=200, verbose_name="Título")),
                ("conteudo", models.TextField(verbose_name="Conteúdo")),
                ("imagem", models.ImageField(blank=True, null=True, upload_to="jornal/", verbose_name="Imagem")),
                ("criado_em", models.DateTimeField(auto_now_add=True, verbose_name="Publicado em")),
                ("autor", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="jornal_posts", to=settings.AUTH_USER_MODEL, verbose_name="Autor")),
            ],
            options={
                "verbose_name": "Postagem do Jornal",
                "verbose_name_plural": "Postagens do Jornal",
                "ordering": ["-criado_em"],
            },
        ),
        migrations.CreateModel(
            name="JornalLeitura",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ultimo_post_visto", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="core.jornalpost", verbose_name="Última postagem vista")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="jornal_leitura", to=settings.AUTH_USER_MODEL, verbose_name="Usuário")),
            ],
            options={
                "verbose_name": "Leitura do Jornal",
                "verbose_name_plural": "Leituras do Jornal",
            },
        ),
    ]
