from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('painel_operacao', '0006_paineloperacaoregistro_observacao_contrato'),
    ]

    operations = [
        migrations.AddField(
            model_name='painelconfiguracao',
            name='dias_uteis_mes',
            field=models.PositiveSmallIntegerField(
                default=22,
                help_text='Informe a quantidade de dias úteis do mês atual. O sistema calcula os dias faltantes automaticamente.',
                verbose_name='Dias úteis do mês vigente',
            ),
        ),
    ]
