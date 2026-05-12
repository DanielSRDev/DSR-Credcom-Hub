from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """
    Altera ChatVinculoOperador.operador de OneToOneField para ForeignKey,
    permitindo que um operador tenha múltiplos supervisores vinculados.

    A unicidade do par (operador, supervisor) é garantida via UniqueConstraint,
    substituindo a constraint implícita do OneToOneField anterior.

    Impacto no banco (PostgreSQL):
    - A coluna operador_id já existe — o ALTER apenas remove o UNIQUE INDEX
      que o OneToOneField criava automaticamente.
    - Nenhum dado é perdido.
    - O related_name muda de chat_vinculo_operador para chat_vinculos_operador:
      qualquer acesso via user.chat_vinculo_operador (fora do chat_interno)
      deve ser atualizado para user.chat_vinculos_operador.all().
    """

    dependencies = [
        ("chat_interno", "0007_chatmonitorconfig"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Altera o campo operador: remove a unicidade do OneToOneField
        #    e passa a ser um ForeignKey comum.
        migrations.AlterField(
            model_name="chatvinculooperador",
            name="operador",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="chat_vinculos_operador",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 2. Adiciona UniqueConstraint no par (operador, supervisor)
        #    para evitar vínculos duplicados.
        migrations.AddConstraint(
            model_name="chatvinculooperador",
            constraint=models.UniqueConstraint(
                fields=["operador", "supervisor"],
                name="uniq_chat_vinculo_operador_supervisor",
            ),
        ),
    ]
