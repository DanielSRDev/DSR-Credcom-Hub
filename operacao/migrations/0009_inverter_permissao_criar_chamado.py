from django.db import migrations, models


def inverter_para_bloqueio(apps, schema_editor):
    """
    Antes: pode_criar_chamado_supervisor (True = pode criar).
    Depois: bloquear_criar_chamado_supervisor (True = bloqueado).

    Para preservar o comportamento de cada usuário existente, o novo
    valor é o inverso do antigo: quem podia (True) fica não-bloqueado
    (False); quem não podia (False) fica bloqueado (True).
    """
    Permissao = apps.get_model("operacao", "OperacaoPermissaoUsuario")
    for p in Permissao.objects.all():
        p.bloquear_criar_chamado_supervisor = not p.bloquear_criar_chamado_supervisor
        p.save(update_fields=["bloquear_criar_chamado_supervisor"])


def reverter_para_permissao(apps, schema_editor):
    """Inverso exato da migração para frente (usado em migrate reverso)."""
    Permissao = apps.get_model("operacao", "OperacaoPermissaoUsuario")
    for p in Permissao.objects.all():
        p.bloquear_criar_chamado_supervisor = not p.bloquear_criar_chamado_supervisor
        p.save(update_fields=["bloquear_criar_chamado_supervisor"])


class Migration(migrations.Migration):

    dependencies = [
        ("operacao", "0008_tarefa_finalizado_automaticamente_and_more"),
    ]

    operations = [
        # 1) renomeia mantendo os valores atuais na coluna
        migrations.RenameField(
            model_name="operacaopermissaousuario",
            old_name="pode_criar_chamado_supervisor",
            new_name="bloquear_criar_chamado_supervisor",
        ),
        # 2) inverte os valores existentes (preserva comportamento por usuário)
        migrations.RunPython(inverter_para_bloqueio, reverter_para_permissao),
        # 3) ajusta default/verbose/help para a nova semântica
        migrations.AlterField(
            model_name="operacaopermissaousuario",
            name="bloquear_criar_chamado_supervisor",
            field=models.BooleanField(
                default=False,
                verbose_name="Bloquear criação de chamado para o supervisor",
                help_text=(
                    "Por padrão, todos podem criar chamado para o supervisor. "
                    "Marque para BLOQUEAR este usuário específico."
                ),
            ),
        ),
    ]
