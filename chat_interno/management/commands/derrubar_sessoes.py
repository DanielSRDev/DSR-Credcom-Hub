from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Apaga todas as sessões ativas, forçando logout de todos os usuários."

    def handle(self, *args, **options):
        total, _ = Session.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"{total} sessão(ões) removida(s)."))
