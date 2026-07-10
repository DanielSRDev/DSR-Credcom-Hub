from collections import defaultdict

from django.db import migrations


def migrar_vinculos(apps, schema_editor):
    """
    Unifica a fonte de equipe: converte os vínculos antigos do chat
    (chat_interno.ChatVinculoOperador: operador -> supervisor) em equipes
    de operacao.Equipe.

    Para cada supervisor, cria/reutiliza uma equipe "Equipe (migrada do chat)
    — <supervisor>" e adiciona o supervisor em `supervisores` e os operadores
    em `membros`. Idempotente (get_or_create pelo nome).

    Nada é apagado de ChatVinculoOperador — apenas espelhado em Equipe.
    """
    Vinculo = apps.get_model("chat_interno", "ChatVinculoOperador")
    Equipe = apps.get_model("operacao", "Equipe")
    User = apps.get_model("auth", "User")

    por_supervisor = defaultdict(list)
    for v in Vinculo.objects.all():
        por_supervisor[v.supervisor_id].append(v.operador_id)

    for sup_id, operador_ids in por_supervisor.items():
        sup = User.objects.filter(id=sup_id).first()
        if not sup:
            continue
        nome = f"Equipe (migrada do chat) — {sup.username}"
        equipe, _ = Equipe.objects.get_or_create(nome=nome, defaults={"ativa": True})
        equipe.supervisores.add(sup_id)
        for oid in operador_ids:
            equipe.membros.add(oid)


def reverter(apps, schema_editor):
    """Remove apenas as equipes criadas por esta migração (pelo prefixo do nome)."""
    Equipe = apps.get_model("operacao", "Equipe")
    Equipe.objects.filter(nome__startswith="Equipe (migrada do chat) —").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operacao", "0009_inverter_permissao_criar_chamado"),
        ("chat_interno", "0012_message_chat_msg_conv_id_idx"),
    ]

    operations = [
        migrations.RunPython(migrar_vinculos, reverter),
    ]
