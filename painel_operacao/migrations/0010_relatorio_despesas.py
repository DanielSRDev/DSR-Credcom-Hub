from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("painel_operacao", "0009_relatorio_valor_entrada"),
    ]

    operations = [
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="despesas",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
    ]
