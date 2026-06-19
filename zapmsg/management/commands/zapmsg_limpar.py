"""
Limpa contatos/conversas do ZapMsg gravados com numero invalido para um usuario.

Uso (rode dentro de backoffice/, com o venv ativo):

    # so LISTA o que seria apagado (nada e removido):
    python manage.py zapmsg_limpar <usuario>

    # apaga de fato os contatos com numero invalido:
    python manage.py zapmsg_limpar <usuario> --confirmar

    # apaga TODAS as conversas do usuario (recomeco do zero):
    python manage.py zapmsg_limpar <usuario> --modo tudo --confirmar

Depois de limpar, as conversas voltam a ser criadas corretamente quando
chegarem novas mensagens (a resolucao de contato ja foi corrigida).
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from zapmsg.models import ZapConta, ZapContato, ZapConversa, ZapMensagem

User = get_user_model()


def numero_valido(wa_id: str) -> bool:
    """True quando o wa_id e um numero brasileiro valido (10/11 digitos) ou
    um identificador que NAO devemos mexer (@lid / @g.us)."""
    wa_id = (wa_id or "").strip().lower()
    if not wa_id:
        return False
    if wa_id.endswith("@lid") or wa_id.endswith("@g.us"):
        return True
    local = wa_id.split("@")[0] if "@" in wa_id else wa_id
    digits = "".join(c for c in local if c.isdigit())
    if digits.startswith("55"):
        digits = digits[2:]
    return len(digits) in (10, 11)


class Command(BaseCommand):
    help = "Limpa contatos/conversas do ZapMsg com numero invalido para um usuario."

    def add_arguments(self, parser):
        parser.add_argument("usuario", help="username do operador")
        parser.add_argument(
            "--modo",
            choices=["invalidos", "tudo"],
            default="invalidos",
            help="invalidos = so os numeros invalidos (padrao); tudo = todas as conversas",
        )
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="aplica a remocao. Sem isso, apenas LISTA (dry-run).",
        )

    def handle(self, *args, **opts):
        # Console do Windows (cp1252) quebra ao imprimir emojis em nomes de
        # contato. Trocamos caracteres nao suportados em vez de estourar.
        try:
            import sys
            sys.stdout.reconfigure(errors="backslashreplace")
        except Exception:
            pass

        username = opts["usuario"]
        modo = opts["modo"]
        confirmar = opts["confirmar"]

        user = User.objects.filter(username__iexact=username).first()
        if not user:
            from django.db.models import Q
            candidatos = User.objects.filter(
                Q(username__icontains=username)
                | Q(first_name__icontains=username)
                | Q(last_name__icontains=username)
            ).order_by("username")[:15]
            linhas = [
                f"Usuario '{username}' nao encontrado.",
                "Use o USERNAME de login (nao o nome completo).",
            ]
            if candidatos:
                linhas.append("")
                linhas.append("Talvez seja um destes (username  |  nome):")
                for u in candidatos:
                    nome = (u.get_full_name() or "").strip()
                    linhas.append(f"   {u.username}  |  {nome}")
            raise CommandError("\n".join(linhas))

        conta = ZapConta.objects.filter(user=user).first()
        if not conta:
            raise CommandError(f"Usuario '{username}' nao tem conta ZapMsg.")

        contatos = list(ZapContato.objects.filter(conta=conta))
        if modo == "invalidos":
            alvos = [c for c in contatos if not numero_valido(c.wa_id)]
        else:
            alvos = contatos

        if not alvos:
            self.stdout.write(self.style.SUCCESS(
                f"Nada a limpar para '{username}' (modo={modo})."
            ))
            return

        self.stdout.write(self.style.WARNING(
            f"Usuario '{username}' | modo={modo} | {len(alvos)} contato(s) alvo:"
        ))
        self.stdout.write("-" * 80)

        total_msgs = 0
        total_convs = 0
        for c in alvos:
            convs = ZapConversa.objects.filter(conta=conta, contato=c)
            n_convs = convs.count()
            n_msgs = ZapMensagem.objects.filter(conversa__in=convs).count()
            total_convs += n_convs
            total_msgs += n_msgs
            self.stdout.write(
                f"  - {c.display_name!r:30} wa_id={c.wa_id!r:24} "
                f"numero={c.numero!r:14} convs={n_convs} msgs={n_msgs}"
            )

        self.stdout.write("-" * 80)
        self.stdout.write(
            f"Total: {len(alvos)} contato(s), {total_convs} conversa(s), {total_msgs} mensagem(ns)."
        )

        if not confirmar:
            self.stdout.write(self.style.NOTICE(
                "\nDRY-RUN: nada foi apagado. Rode de novo com --confirmar para aplicar."
            ))
            return

        with transaction.atomic():
            ids = [c.id for c in alvos]
            convs = ZapConversa.objects.filter(conta=conta, contato_id__in=ids)
            ZapMensagem.objects.filter(conversa__in=convs).delete()
            convs.delete()
            ZapContato.objects.filter(id__in=ids).delete()

        self.stdout.write(self.style.SUCCESS(
            f"\nLimpeza concluida: {len(alvos)} contato(s) removido(s) para '{username}'."
        ))
