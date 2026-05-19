"""
Gestao/migrations/0008_tarefa_codigo_pendente.py  — VERSÃO CORRIGIDA

Problema original: usava Tarefa.all_objects dentro do RunPython, mas
modelos históricos não carregam managers customizados — só o default.

Solução: usar schema_editor.connection para executar SQL direto na
função de população, garantindo que TODOS os registros (inclusive
soft-deleted) recebam código, sem depender de nenhum manager.
"""
from django.db import migrations, models


def gerar_codigos_gestao(apps, schema_editor):
    """
    Popula 'codigo' para todos os registros existentes (incluindo soft-deleted).
    Usa _meta.db_table para pegar o nome real da tabela — evita problema de
    case-sensitivity no PostgreSQL com app_label 'Gestao' maiúsculo.
    """
    Tarefa = apps.get_model("Gestao", "Tarefa")
    table_name = Tarefa._meta.db_table  # ex: 'Gestao_tarefa'

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'SELECT id FROM "{table_name}" ORDER BY id')
        rows = cursor.fetchall()
        for (pk,) in rows:
            codigo = f"GES-{pk:05d}"
            cursor.execute(
                f'UPDATE "{table_name}" SET codigo = %s WHERE id = %s',
                [codigo, pk],
            )


class Migration(migrations.Migration):

    dependencies = [
        ("Gestao", "0007_tarefa_deleted_at_tarefa_deleted_by"),
    ]

    operations = [
        # 1. Adiciona campo codigo temporariamente nullable
        migrations.AddField(
            model_name="tarefa",
            name="codigo",
            field=models.CharField(blank=True, max_length=20, verbose_name="Código"),
        ),
        # 2. Popula via SQL direto (sem depender de managers)
        migrations.RunPython(gerar_codigos_gestao, migrations.RunPython.noop),
        # 3. Torna único e não-nulo
        migrations.AlterField(
            model_name="tarefa",
            name="codigo",
            field=models.CharField(
                max_length=20,
                unique=True,
                verbose_name="Código",
                help_text="Identificador único do card (ex: GES-00001). Gerado automaticamente.",
            ),
        ),
        # 4. Adiciona pendente_em
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
