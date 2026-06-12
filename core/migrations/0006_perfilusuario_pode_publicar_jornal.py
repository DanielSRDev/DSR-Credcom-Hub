from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_jornal"),
    ]

    operations = [
        migrations.AddField(
            model_name="perfilusuario",
            name="pode_publicar_jornal",
            field=models.BooleanField(
                default=False,
                verbose_name="Pode publicar no Jornal",
                help_text="Marque para permitir que este usuário publique novidades no Jornal.",
            ),
        ),
    ]
