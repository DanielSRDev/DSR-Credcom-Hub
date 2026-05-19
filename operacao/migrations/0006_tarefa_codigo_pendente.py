"""
operacao/migrations/0006_tarefa_codigo_pendente.py  — VERSÃO CORRIGIDA
"""
from django.db import migrations, models


def gerar_codigos_operacao(apps, schema_editor):
    Tarefa = apps.get_model("operacao", "Tarefa")
    table_name = Tarefa._meta.db_table  # 'operacao_tarefa'

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'SELECT id FROM "{table_name}" ORDER BY id')
        rows = cursor.fetchall()
        for (pk,) in rows:
            codigo = f"OPE-{pk:05d}"
            cursor.execute(
                f'UPDATE "{table_name}" SET codigo = %s WHERE id = %s',
                [codigo, pk],
            )


class Migration(migrations.Migration):

    dependencies = [
        ("operacao", "0005_remove_equipe_supervisor_equipe_supervisores"),
    ]

    operations = [
        migrations.AddField(
            model_name="tarefa",
            name="codigo",
            field=models.CharField(blank=True, max_length=20, verbose_name="Código"),
        ),
        migrations.RunPython(gerar_codigos_operacao, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tarefa",
            name="codigo",
            field=models.CharField(
                max_length=20,
                unique=True,
                verbose_name="Código",
                help_text="Identificador único do chamado (ex: OPE-00001). Gerado automaticamente.",
            ),
        ),
        migrations.AddField(
            model_name="tarefa",
            name="pendente_em",
            field=models.DateTimeField(
                null=True,
                blank=True,
                verbose_name="Devolvido com pendência em",
            ),
        ),
    ]
