from django.core.management.base import BaseCommand
from painel_operacao.services import (
    sincronizar_painel_operacao,
    sincronizar_relatorio_geral
)


class Command(BaseCommand):
    help = "Atualiza Painel + Relatório Geral"

    def add_arguments(self, parser):
        parser.add_argument("--data-ini", required=True, type=str)
        parser.add_argument("--data-fim", required=True, type=str)

    def handle(self, *args, **options):
        data_ini = options["data_ini"]
        data_fim = options["data_fim"]

        self.stdout.write(self.style.WARNING("🔄 Iniciando atualização completa..."))

        # 1️⃣ Painel (emissão)
        resultado_painel = sincronizar_painel_operacao(
            data_ini=data_ini,
            data_fim=data_fim
        )

        self.stdout.write(self.style.SUCCESS(f"✅ Painel: {resultado_painel.get('mensagem', 'OK')}"))

        # 2️⃣ Relatório geral (pagamentos + cruzamento)
        resultado_relatorio = sincronizar_relatorio_geral(
            data_ini=data_ini,
            data_fim=data_fim
        )

        self.stdout.write(self.style.SUCCESS(f"📊 Relatório Geral: {resultado_relatorio.get('mensagem', 'OK')}"))

        self.stdout.write(self.style.SUCCESS("🚀 Atualização completa finalizada!"))