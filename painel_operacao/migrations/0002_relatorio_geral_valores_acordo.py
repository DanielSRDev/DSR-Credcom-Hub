# Generated manually for painel_operacao export fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("painel_operacao", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="principal_liquido",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="multa_liquida",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="juros_liquido",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="valor_parcela",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="valor_total_acordo",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
    ]
