"""
Finaliza automaticamente os cards EXECUTADO que estouraram o prazo de validação,
nos módulos Operação e Gestão.

Pode ser agendado no Agendador de Tarefas do Windows:
    python manage.py auto_finalizar_cards
"""
from django.core.management.base import BaseCommand

from core.services import finalizar_executados_vencidos


class Command(BaseCommand):
    help = "Finaliza cards EXECUTADO vencidos (Operação e Gestão)."

    def handle(self, *args, **options):
        from operacao.models import Tarefa as OpTarefa, Comentario as OpComentario
        from Gestao.models import Tarefa as GeTarefa, Comentario as GeComentario

        n_op = finalizar_executados_vencidos(OpTarefa, OpComentario)
        n_ge = finalizar_executados_vencidos(GeTarefa, GeComentario)

        self.stdout.write(self.style.SUCCESS(
            f"Operação: {n_op} card(s) finalizado(s). "
            f"Gestão: {n_ge} card(s) finalizado(s)."
        ))
