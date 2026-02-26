from __future__ import annotations

from typing import Dict, List

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from .models import ChatVinculoOperador, Conversation, Message


User = get_user_model()

# ====== Regras de permissão (por Grupo) ======
GRP_OPERACAO = "OPERACAO"
GRP_SUPERVISOR = "OPERACAO_SUPERVISOR"
GRP_CORDENACAO = "OPERACAO_CORDENACAO"

ONLINE_TTL_SECONDS = 90  # ping a cada ~20-30s, TTL curto pra "online" ser real


def _has_group(user, group_name: str) -> bool:
    try:
        return user.groups.filter(name=group_name).exists()
    except Exception:
        return False


def get_role(user) -> str:
    """
    Precedência: Coordenação > Supervisor > Operação > Other
    """
    if getattr(user, "is_superuser", False):
        return "SUPERUSER"
    if _has_group(user, GRP_CORDENACAO):
        return "CORDENACAO"
    if _has_group(user, GRP_SUPERVISOR):
        return "SUPERVISOR"
    if _has_group(user, GRP_OPERACAO):
        return "OPERACAO"
    return "OTHER"


# ====== Online ======

def ping_user(user) -> None:
    if not user or not getattr(user, "is_authenticated", False):
        return
    cache.set(f"chat_online:{user.id}", timezone.now().timestamp(), timeout=ONLINE_TTL_SECONDS)


def is_online(user_id: int) -> bool:
    if not user_id:
        return False
    return cache.get(f"chat_online:{user_id}") is not None


# ====== Contatos permitidos (SUA REGRA) ======

def allowed_contacts(user):
    """
    Regra solicitada:

    - OPERACAO:
        manda/recebe de OPERACAO_SUPERVISOR e OPERACAO_CORDENACAO
    - OPERACAO_SUPERVISOR:
        manda/recebe da sua equipe (vínculo),
        de OPERACAO_CORDENACAO e de outros supervisores
    - OPERACAO_CORDENACAO:
        fala com todo mundo e vê todo mundo
    """
    if not user or not getattr(user, "is_authenticated", False):
        return User.objects.none()

    qs = User.objects.filter(is_active=True).exclude(id=user.id)
    role = get_role(user)

    if role in ("SUPERUSER", "CORDENACAO"):
        return qs

    if role == "OPERACAO":
        return qs.filter(groups__name__in=[GRP_CORDENACAO, GRP_SUPERVISOR]).distinct()

    if role == "SUPERVISOR":
        equipe_ids = list(
            ChatVinculoOperador.objects.filter(supervisor=user).values_list("operador_id", flat=True)
        )
        return qs.filter(
            Q(groups__name=GRP_CORDENACAO) |
            Q(groups__name=GRP_SUPERVISOR) |
            Q(id__in=equipe_ids)
        ).distinct()

    return User.objects.none()


def can_send_to(sender, receiver) -> bool:
    if not sender or not getattr(sender, "is_authenticated", False):
        return False
    if not receiver or not getattr(receiver, "is_active", False):
        return False
    if sender.id == receiver.id:
        return False

    s_role = get_role(sender)
    if s_role in ("SUPERUSER", "CORDENACAO"):
        return True

    return allowed_contacts(sender).filter(id=receiver.id).exists()


# ====== Conversas e mensagens ======

def get_or_create_conversation(user_a, user_b) -> Conversation:
    if user_a.id == user_b.id:
        raise ValueError("Não existe conversa com você mesmo.")

    a, b = (user_a, user_b) if user_a.id < user_b.id else (user_b, user_a)

    conv = (
        Conversation.objects.filter(Q(user1=a, user2=b) | Q(user1=b, user2=a))
        .select_related("user1", "user2")
        .first()
    )
    if conv:
        return conv

    return Conversation.objects.create(user1=a, user2=b)


def send_message(sender, receiver, texto: str) -> Message:
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("Mensagem vazia.")
    if not can_send_to(sender, receiver):
        raise PermissionError("Sem permissão para enviar para este usuário.")

    conv = get_or_create_conversation(sender, receiver)
    return Message.objects.create(conversation=conv, sender=sender, texto=texto)


def mark_read(user, other) -> int:
    conv = get_or_create_conversation(user, other)
    now = timezone.now()
    qs = Message.objects.filter(conversation=conv, sender=other, lido_em__isnull=True)
    return qs.update(lido_em=now)


# ====== Não lidas ======

def unread_count(user) -> int:
    if not user or not getattr(user, "is_authenticated", False):
        return 0
    return Message.objects.filter(
        Q(conversation__user1=user) | Q(conversation__user2=user),
        lido_em__isnull=True,
    ).exclude(sender=user).count()


def unread_by_contact(user) -> Dict[int, int]:
    if not user or not getattr(user, "is_authenticated", False):
        return {}

    rows = (
        Message.objects.filter(
            Q(conversation__user1=user) | Q(conversation__user2=user),
            lido_em__isnull=True,
        )
        .exclude(sender=user)
        .values("sender_id")
        .annotate(c=Count("id"))
    )
    return {r["sender_id"]: int(r["c"]) for r in rows}


# ====== Compat (nomes que suas views.py já usam) ======

def list_messages_between(user, other, limit: int = 80):
    conv = get_or_create_conversation(user, other)
    msgs = (
        Message.objects.filter(conversation=conv)
        .select_related("sender")
        .order_by("criado_em")[: max(1, min(limit, 500))]
    )
    return list(msgs), conv


def send_text(sender, receiver, texto: str) -> Message:
    return send_message(sender, receiver, texto)


def mark_read_conversation(user, other) -> int:
    return mark_read(user, other)