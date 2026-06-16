from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nibo_panel', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CredorVisivel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('credor_id', models.BigIntegerField(unique=True)),
                ('sigla', models.CharField(blank=True, max_length=50, null=True)),
                ('ativo', models.BooleanField(default=True)),
                ('ordem', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'nibo_credor_visivel',
                'ordering': ['ordem', 'credor_id'],
                'verbose_name': 'Credor visível (Painel Nibo)',
                'verbose_name_plural': 'Credores visíveis (Painel Nibo)',
            },
        ),
    ]
