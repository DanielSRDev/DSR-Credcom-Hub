# Generated manually for painel_operacao acompanhamento geral.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("painel_operacao", "0002_relatorio_geral_valores_acordo"),
    ]

    operations = [
        migrations.CreateModel(
            name="MetaOperadorCarteira",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ano", models.PositiveIntegerField(db_index=True, verbose_name="Ano")),
                ("mes", models.PositiveSmallIntegerField(db_index=True, verbose_name="Mês")),
                ("operador_login", models.CharField(blank=True, db_index=True, default="", max_length=255, verbose_name="Login do operador")),
                ("operador_nome", models.CharField(db_index=True, max_length=255, verbose_name="Nome do operador")),
                ("meta_mensal", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Meta mensal")),
                ("ativo", models.BooleanField(default=True, verbose_name="Ativo")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Atualizado em")),
                ("carteira", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metas_operadores", to="painel_operacao.carteirasupervisor", verbose_name="Carteira")),
            ],
            options={
                "verbose_name": "Meta por Operador e Carteira",
                "verbose_name_plural": "Metas por Operador e Carteira",
                "ordering": ["-ano", "-mes", "carteira__credor_nome", "operador_nome"],
            },
        ),
        migrations.AddIndex(
            model_name="metaoperadorcarteira",
            index=models.Index(fields=["ano", "mes", "ativo"], name="painel_oper_ano_mes_93203f_idx"),
        ),
        migrations.AddIndex(
            model_name="metaoperadorcarteira",
            index=models.Index(fields=["operador_nome"], name="painel_oper_operado_0c8d41_idx"),
        ),
        migrations.AddIndex(
            model_name="metaoperadorcarteira",
            index=models.Index(fields=["operador_login"], name="painel_oper_operado_bcd862_idx"),
        ),
        migrations.AddConstraint(
            model_name="metaoperadorcarteira",
            constraint=models.UniqueConstraint(fields=("ano", "mes", "carteira", "operador_login", "operador_nome"), name="uniq_meta_operador_carteira_mes"),
        ),
    ]
