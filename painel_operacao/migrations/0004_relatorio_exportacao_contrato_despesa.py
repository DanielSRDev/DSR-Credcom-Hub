from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("painel_operacao", "0003_metaoperadorcarteira"),
    ]

    operations = [
        migrations.AddField(
            model_name="paineloperacaoregistro",
            name="con_id",
            field=models.BigIntegerField("Contrato ID", blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="paineloperacaoregistro",
            name="despesa_liquida",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="con_id",
            field=models.BigIntegerField("Contrato ID", blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="despesa_liquida",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="paineloperacaorelatoriogeral",
            name="valor_pagamento_periodo",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
    ]
