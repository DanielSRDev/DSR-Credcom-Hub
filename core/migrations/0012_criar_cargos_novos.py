from django.db import migrations

# Cargos canônicos garantidos por esta migração.
# Hardcoded (migrations devem ser auto-contidas, sem importar app code).
# Ver core/grupos.py para a fonte usada no código de runtime.
CARGOS = [
    "GESTAO",
    "GESTAO_GESTOR",
    "POS_ACORDO",
    "OPERACAO",
    "FINANCEIRO",
    "JURIDICO",
]


def criar_cargos(apps, schema_editor):
    """
    Garante que os 6 cargos canônicos existam como grupos.
    Apenas cria os que faltam (POS_ACORDO, JURIDICO e FINANCEIRO eram
    inexistentes). Não toca nos grupos já existentes nem nos legados.
    """
    Group = apps.get_model("auth", "Group")
    for nome in CARGOS:
        Group.objects.get_or_create(name=nome)


def reverter(apps, schema_editor):
    """
    Remove apenas os cargos novos e SOMENTE se estiverem vazios
    (sem usuários vinculados), para nunca apagar grupo em uso.
    Os cargos que já existiam antes (GESTAO, GESTAO_GESTOR, OPERACAO)
    não são tocados.
    """
    Group = apps.get_model("auth", "Group")
    for nome in ("POS_ACORDO", "JURIDICO", "FINANCEIRO"):
        grupo = Group.objects.filter(name=nome).first()
        if grupo and not grupo.user_set.exists():
            grupo.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_usuarioliberacaomodulo"),
    ]

    operations = [
        migrations.RunPython(criar_cargos, reverter),
    ]
