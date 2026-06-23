"""
Envia automaticamente para o Nibo os lancamentos do DIA UTIL ANTERIOR que
ainda estao com enviado=FALSE.

Regra de data:
  - data alvo = dia util anterior a data de referencia (hoje, por padrao).
  - segunda-feira -> envia sexta-feira (pula sabado/domingo).

Uso:
  python manage.py nibo_enviar_dia_anterior              # envia o dia util anterior
  python manage.py nibo_enviar_dia_anterior --dry-run    # so simula (nao envia)
  python manage.py nibo_enviar_dia_anterior --data 2026-06-16   # envia uma data especifica
"""

from datetime import date, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from nibo_panel.services.remessa import enviar_periodo, gravar_csv_auditoria


def dia_util_anterior(referencia=None):
    """Retorna o dia util (seg-sex) imediatamente anterior a 'referencia'."""
    if referencia is None:
        referencia = date.today()
    d = referencia - timedelta(days=1)
    while d.weekday() >= 5:  # 5=sabado, 6=domingo
        d -= timedelta(days=1)
    return d


def _registrar_log(linhas):
    """Grava um log da execucao em var/nibo_remessa/ (mesmo padrao do stage)."""
    try:
        base_dir = Path(getattr(settings, "BASE_DIR", Path(".")))
        out_dir = base_dir / "var" / "nibo_remessa"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"remessa_{ts}.log"
        out_path.write_text("\n".join(linhas), encoding="utf-8")
        return out_path
    except Exception:
        return None


class Command(BaseCommand):
    help = "Envia ao Nibo os lancamentos NAO enviados do dia util anterior."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data",
            type=str,
            default=None,
            help="Data especifica YYYY-MM-DD (ignora a regra de dia util anterior).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="So simula: lista o que seria enviado, sem chamar a API nem marcar enviado.",
        )

    def handle(self, *args, **opts):
        if opts.get("data"):
            try:
                data_alvo = datetime.strptime(opts["data"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--data invalida. Use o formato YYYY-MM-DD.")
        else:
            data_alvo = dia_util_anterior()

        dry_run = opts["dry_run"]

        cabecalho = (
            f"[{timezone.localtime():%d/%m/%Y %H:%M:%S}] "
            f"Remessa Nibo {'(DRY-RUN) ' if dry_run else ''}| data alvo: {data_alvo:%d/%m/%Y}"
        )
        self.stdout.write(self.style.WARNING(cabecalho))

        rep = enviar_periodo(data_alvo, data_alvo, dry_run=dry_run)

        resumo = (
            f"Processados: {rep.processados} | "
            f"Avisos/pulados: {rep.total_avisos} | Erros: {rep.total_erros}"
        )
        self.stdout.write(self.style.SUCCESS(resumo))

        for a in rep.avisos:
            self.stdout.write(f"  [aviso] {a}")
        for e in rep.erros:
            self.stdout.write(self.style.ERROR(f"  [erro] {e}"))

        linhas = [cabecalho, resumo, "", "AVISOS/PULADOS:"]
        linhas += [f"  {a}" for a in rep.avisos] or ["  (nenhum)"]
        linhas += ["", "ERROS:"]
        linhas += [f"  {e}" for e in rep.erros] or ["  (nenhum)"]
        caminho = _registrar_log(linhas)
        if caminho:
            self.stdout.write(f"Log salvo em: {caminho}")

        # CSV de auditoria: uma linha por lancamento efetivamente enviado.
        csv_path = gravar_csv_auditoria(rep.enviados)
        if csv_path:
            self.stdout.write(self.style.SUCCESS(f"Auditoria CSV ({len(rep.enviados)} envios): {csv_path}"))

        return resumo
