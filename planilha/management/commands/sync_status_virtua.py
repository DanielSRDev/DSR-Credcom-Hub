from django.core.management.base import BaseCommand

from planilha.services import sincronizar_status_virtua


class Command(BaseCommand):
    help = "Sincroniza o Status Atual dos contratos com o último evento de cobrança do Virtua"

    def handle(self, *args, **options):
        resultado = sincronizar_status_virtua()
        self.stdout.write(self.style.SUCCESS(
            f"Base: {resultado['total_base']} nr_contrato distintos | "
            f"Com evento no mês atual: {resultado['encontrados']} | "
            f"Atualizados: {resultado['atualizados']} | "
            f"Limpos (sem evento no mês): {resultado['limpos']}"
        ))
