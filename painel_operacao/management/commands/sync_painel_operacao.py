from datetime import date, timedelta
from django.core.management.base import BaseCommand

from painel_operacao.services import sincronizar_painel_operacao


class Command(BaseCommand):
    help = "Sincroniza dados do Painel Operação"

    def add_arguments(self, parser):
        parser.add_argument("--data-ini", type=str, help="Data inicial no formato YYYY-MM-DD")
        parser.add_argument("--data-fim", type=str, help="Data final no formato YYYY-MM-DD")

    def handle(self, *args, **options):
        data_fim = date.fromisoformat(options["data_fim"]) if options.get("data_fim") else date.today()
        data_ini = date.fromisoformat(options["data_ini"]) if options.get("data_ini") else (data_fim - timedelta(days=30))

        resultado = sincronizar_painel_operacao(data_ini=data_ini, data_fim=data_fim)
        self.stdout.write(self.style.SUCCESS(resultado["mensagem"]))