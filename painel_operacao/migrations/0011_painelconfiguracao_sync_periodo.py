from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("painel_operacao", "0010_relatorio_despesas"),
    ]

    operations = [
        migrations.AddField(
            model_name="painelconfiguracao",
            name="sync_data_ini",
            field=models.DateField(
                blank=True,
                help_text="Início do período usado pelo botão 'Atualizar dados'. Deixe em branco para usar o 1º dia do mês atual.",
                null=True,
                verbose_name="Data inicial do sync",
            ),
        ),
        migrations.AddField(
            model_name="painelconfiguracao",
            name="sync_data_fim",
            field=models.DateField(
                blank=True,
                help_text="Fim do período usado pelo botão 'Atualizar dados'. Deixe em branco para usar a data de hoje.",
                null=True,
                verbose_name="Data final do sync",
            ),
        ),
    ]
