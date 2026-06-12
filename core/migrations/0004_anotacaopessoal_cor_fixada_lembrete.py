from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_anotacaopessoal_financeiro"),
    ]

    operations = [
        migrations.AddField(
            model_name="anotacaopessoal",
            name="cor",
            field=models.CharField(
                choices=[
                    ("padrao", "Padrão"),
                    ("amarelo", "Amarelo"),
                    ("verde", "Verde"),
                    ("azul", "Azul"),
                    ("rosa", "Rosa"),
                    ("vermelho", "Vermelho"),
                ],
                default="padrao",
                max_length=10,
                verbose_name="Cor",
            ),
        ),
        migrations.AddField(
            model_name="anotacaopessoal",
            name="fixada",
            field=models.BooleanField(default=False, verbose_name="Fixada"),
        ),
        migrations.AddField(
            model_name="anotacaopessoal",
            name="lembrete_em",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Lembrar em"),
        ),
        migrations.AlterModelOptions(
            name="anotacaopessoal",
            options={
                "ordering": ["concluida", "-fixada", "-criado_em"],
                "verbose_name": "Anotação pessoal",
                "verbose_name_plural": "Anotações pessoais",
            },
        ),
    ]
