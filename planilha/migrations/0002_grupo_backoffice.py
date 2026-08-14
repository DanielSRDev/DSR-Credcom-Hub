from django.db import migrations


def criar_grupo_backoffice(apps, schema_editor):
    """Cria o grupo 'Backoffice', que libera a importação de bases no módulo Planilha."""
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="Backoffice")


def remover_grupo_backoffice(apps, schema_editor):
    """Remove o grupo apenas se estiver vazio (sem usuários), para não apagar em uso."""
    Group = apps.get_model("auth", "Group")
    grupo = Group.objects.filter(name="Backoffice").first()
    if grupo and not grupo.user_set.exists():
        grupo.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("planilha", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(criar_grupo_backoffice, remover_grupo_backoffice),
    ]
