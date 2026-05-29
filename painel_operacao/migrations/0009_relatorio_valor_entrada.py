from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("painel_operacao", "0008_taxa_liquida"),
    ]

    operations = [
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="valor_entrada",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
    ]
