from __future__ import annotations

from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Q, Count

from .models import Conversation, Message, ChatVinculoOperador, ChatPresence

User = get_user_model()

ONLINE_TTL_SECONDS = 60

# =========================
# REGRAS DE CONTATO / ENVIO
# =========================

def _in_group(user, name: str) -> bool:
    return user.groups.filter(name=name).exists()


def allowed_contacts(user):
    """
    Regras:
    - Coordenação: fala com todos
    - Supervisor: fala com equipe + supervisores + coordenação
    - Operação: fala só com supervisor + coordenação
    """
    qs = User.objects.filter(is_active=True).exclude(id=user.id)

    is_coord = _in_group(user, "OPERACAO_CORDENACAO")
    is_sup = _in_group(user, "OPERACAO_SUPERVISOR")
    is_oper = _in_group(user, "OPERACAO")

    if is_coord:
        return qs

    if is_sup:
        sup_ids = User.objects.filter(groups__name="OPERACAO_SUPERVISOR").values_list("id", flat=True)
        coord_ids = User.objects.filter(groups__name="OPERACAO_CORDENACAO").values_list("id", flat=True)
        equipe_ids = ChatVinculoOperador.objects.filter(supervisor=user).values_list("operador_id", flat=True)

        return qs.filter(
            Q(id__in=sup_ids) | Q(id__in=coord_ids) | Q(id__in=equipe_ids)
        ).distinct()

    if is_oper:
        vinc = ChatVinculoOperador.objects.filter(operador=user).first()
        coord_ids = User.objects.filter(groups__name="OPERACAO_CORDENACAO").values_list("id", flat=True)

        if not vinc:
            return qs.filter(id__in=coord_ids)

        return qs.filter(Q(id=vinc.supervisor_id) | Q(id__in=coord_ids)).distinct()

    return qs.none()


def can_send_to(me, other) -> bool:
    return allowed_contacts(me).filter(id=other.id).exists()


# ==========
# PRESENÇA
# ==========

def _get_presence(user):
    """
    Presence persistente no banco (não depende de memória do processo).
    - status: online/ausente/offline (preferência do usuário)
    - updated_at: usado como "último ping" para saber se está ativo de verdade
    """
    presence, _ = ChatPresence.objects.get_or_create(user=user)
    return presence


def ping_user(user):
    """
    Atualiza o heartbeat do usuário.
    NÃO muda o status escolhido (online/ausente/offline) — só atualiza o updated_at.
    """
    presence = _get_presence(user)
    # auto_now atualiza no save()
    presence.save(update_fields=["updated_at"])


def effective_status(user) -> str:
    """
    Status efetivo pra UI:
    - Se usuário marcou OFFLINE: sempre offline.
    - Se o último ping passou do TTL: offline (mesmo que ele tenha marcado online/ausente).
    - Caso contrário, respeita o status escolhido: online ou ausente.
    """
    presence = _get_presence(user)

    if presence.status == ChatPresence.Status.OFFLINE:
        return "offline"

    # sem ping recente => offline
    if timezone.now() - presence.updated_at > timedelta(seconds=ONLINE_TTL_SECONDS):
        return "offline"

    if presence.status == ChatPresence.Status.AUSENTE:
        return "ausente"

    return "online"


def is_online(user_id: int) -> bool:
    """
    Mantém compatibilidade com código antigo que espera boolean.
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return False
    return effective_status(user) == "online"


# ==========
# CONVERSA
# ==========

def _get_or_create_conversation(u1, u2):
    a, b = (u1, u2) if u1.id < u2.id else (u2, u1)
    conv, _ = Conversation.objects.get_or_create(user1=a, user2=b)
    return conv


def list_messages_between(me, other):
    conv = _get_or_create_conversation(me, other)
    msgs = conv.messages.select_related("sender").all()
    return msgs, conv


# ==========
# UNREAD (CERTINHO)
# ==========

def unread_by_contact(user):
    """
    Retorna {other_user_id: qtd_nao_lidas}
    IMPORTANTE: só conta mensagens recebidas (sender != user).
    """
    conv_qs = Conversation.objects.filter(Q(user1=user) | Q(user2=user))

    qs = Message.objects.filter(
        conversation__in=conv_qs,
        lido_em__isnull=True,
    ).exclude(sender=user)  # <-- ESSENCIAL: não conta as que eu enviei

    # Como é 1:1, o "sender_id" é o outro usuário (quem me enviou)
    data = qs.values("sender_id").annotate(c=Count("id"))
    return {row["sender_id"]: row["c"] for row in data}


def unread_count(user) -> int:
    """
    Total de não-lidas para badge da navbar.
    Só conta o que o usuário RECEBEU e ainda não leu.
    """
    conv_qs = Conversation.objects.filter(Q(user1=user) | Q(user2=user))

    return Message.objects.filter(
        conversation__in=conv_qs,
        lido_em__isnull=True,
    ).exclude(sender=user).count()  # <-- ESSENCIAL


def mark_read_conversation(me, other) -> int:
    """
    Marca como lidas só mensagens do OUTRO pra MIM.
    """
    conv = _get_or_create_conversation(me, other)

    qs = conv.messages.filter(
        lido_em__isnull=True
    ).exclude(sender=me)  # <-- só o que eu RECEBI

    return qs.update(lido_em=timezone.now())


# ==========
# ENVIO
# ==========

def send_text(me, other, texto: str, imagem=None):
    conv = _get_or_create_conversation(me, other)
    msg = Message.objects.create(
        conversation=conv,
        sender=me,
        texto=texto or "",
        imagem=imagem if imagem else None,
    )
    return msg