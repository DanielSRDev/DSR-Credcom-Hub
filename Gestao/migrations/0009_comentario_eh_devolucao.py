from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("Gestao", "0008_tarefa_codigo_pendente")]
    operations = [
        migrations.AddField(
            model_name="comentario",
            name="eh_devolucao",
            field=models.BooleanField(default=False, verbose_name="É comentário de devolução"),
        ),
    ]
