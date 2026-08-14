from django.db import migrations

PADROES = [
    "Sem contato",
    "Ligação - sem sucesso",
    "Ligação - contato realizado",
    "WhatsApp enviado",
    "Promessa de pagamento",
    "Negociação em andamento",
    "Pagou",
    "Recusou / não quer negociar",
]


def seed(apps, schema_editor):
    Status = apps.get_model("planilha", "PlanilhaStatusAcionamento")
    for i, nome in enumerate(PADROES, start=1):
        Status.objects.get_or_create(nome=nome, defaults={"ordem": i, "ativo": True})


def remover(apps, schema_editor):
    Status = apps.get_model("planilha", "PlanilhaStatusAcionamento")
    Status.objects.filter(nome__in=PADROES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("planilha", "0004_planilhastatusacionamento_planilhaacionamento"),
    ]

    operations = [
        migrations.RunPython(seed, remover),
    ]
