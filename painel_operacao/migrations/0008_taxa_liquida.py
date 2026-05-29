from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("painel_operacao", "0007_painelconfiguracao_dias_uteis_mes"),
    ]

    operations = [
        migrations.AddField(
            model_name="paineloperacaoregistro",
            name="taxa_liquida",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="taxa_liquida",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
    ]
