from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat_interno", "0003_delete_chatpresence"),
    ]

    operations = [
        migrations.AlterField(
            model_name="message",
            name="texto",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="message",
            name="imagem",
            field=models.FileField(blank=True, null=True, upload_to="chat_interno/img/"),
        ),
    ]
