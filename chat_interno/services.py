from __future__ import annotations

from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Q, Count

from .models import Conversation, Message, MessageReaction, ChatVinculoOperador, ChatPresence, ChatBloqueio, ChatLiberacao, ChatLiberacaoGrupo

User = get_user_model()

ONLINE_TTL_SECONDS = 120

# =========================
# REGRAS DE CONTATO / ENVIO
# =========================

def _in_group(user, name: str) -> bool:
    return user.groups.filter(name=name).exists()


def _ids_bloqueados(user):
    """
    Retorna set de IDs bloqueados para este usuário.
    Superuser não tem bloqueios aplicados.
    """
    if user.is_superuser:
        return set()
    como_a = ChatBloqueio.objects.filter(user_a=user).values_list("user_b_id", flat=True)
    como_b = ChatBloqueio.objects.filter(user_b=user).values_list("user_a_id", flat=True)
    return set(como_a) | set(como_b)


def _ids_liberados(user):
    """
    Retorna set de IDs com liberação explícita para este usuário.
    Inclui liberações individuais (ChatLiberacao) e em grupo (ChatLiberacaoGrupo).
    Superuser não precisa — já vê todos.
    """
    if user.is_superuser:
        return set()

    # liberações individuais
    como_a = ChatLiberacao.objects.filter(user_a=user).values_list("user_b_id", flat=True)
    como_b = ChatLiberacao.objects.filter(user_b=user).values_list("user_a_id", flat=True)
    ids = set(como_a) | set(como_b)

    # grupão: o usuário É o central → todos os membros (ou todos os ativos) são liberados
    libs_central = ChatLiberacaoGrupo.objects.filter(usuario=user)
    if libs_central.filter(para_todos=True).exists():
        ids |= set(User.objects.filter(is_active=True).exclude(id=user.id).values_list("id", flat=True))
    else:
        for lib in libs_central:
            ids |= set(lib.membros.filter(is_active=True).exclude(id=user.id).values_list("id", flat=True))

    # grupão: o usuário É membro do grupão de alguém → esse alguém é liberado
    from django.db.models import Q as _Q
    libs_como_membro = ChatLiberacaoGrupo.objects.filter(
        _Q(membros=user) | _Q(para_todos=True)
    ).exclude(usuario=user).values_list("usuario_id", flat=True)
    ids |= set(libs_como_membro)

    return ids


def can_send_broadcast(user) -> bool:
    """Verifica se o usuário pode enviar mensagem em massa."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    cfg = getattr(user, "chat_monitor_config", None)
    return bool(cfg and cfg.pode_enviar_massa)


def allowed_contacts(user):
    """
    Regras de contato:
    - Coordenação: fala com todos.
    - Supervisor: fala com outros supervisores + coordenação + sua equipe vinculada.
    - Operação: fala com TODOS os seus supervisores vinculados + coordenação.
                Se não tiver nenhum vínculo, fala apenas com a coordenação.

    Exceções aplicadas APÓS as regras de cargo (em ordem):
    1. ChatLiberacao: adiciona usuários ao resultado, mesmo fora do cargo permitido.
    2. ChatBloqueio: remove usuários do resultado, EXCETO se houver liberação explícita.

    Superuser não é afetado por nenhuma dessas regras.
    """
    qs_base = User.objects.filter(is_active=True).exclude(id=user.id)

    liberados = _ids_liberados(user)
    bloqueados = _ids_bloqueados(user)

    # Bloqueios não se aplicam a pares com liberação explícita
    bloqueados_efetivos = bloqueados - liberados

    is_coord = _in_group(user, "OPERACAO_CORDENACAO")
    is_sup   = _in_group(user, "OPERACAO_SUPERVISOR")
    is_oper  = _in_group(user, "OPERACAO")

    # ── monta queryset por cargo ──────────────────────────────────────
    if is_coord:
        qs_cargo = qs_base

    elif is_sup:
        sup_ids   = User.objects.filter(groups__name="OPERACAO_SUPERVISOR").values_list("id", flat=True)
        coord_ids = User.objects.filter(groups__name="OPERACAO_CORDENACAO").values_list("id", flat=True)
        equipe_ids = ChatVinculoOperador.objects.filter(supervisor=user).values_list("operador_id", flat=True)
        qs_cargo = qs_base.filter(
            Q(id__in=sup_ids) | Q(id__in=coord_ids) | Q(id__in=equipe_ids)
        ).distinct()

    elif is_oper:
        coord_ids      = User.objects.filter(groups__name="OPERACAO_CORDENACAO").values_list("id", flat=True)
        supervisor_ids = ChatVinculoOperador.objects.filter(operador=user).values_list("supervisor_id", flat=True)

        if not supervisor_ids:
            qs_cargo = qs_base.filter(id__in=coord_ids)
        else:
            qs_cargo = qs_base.filter(
                Q(id__in=supervisor_ids) | Q(id__in=coord_ids)
            ).distinct()

    else:
        qs_cargo = qs_base.none()

    # ── aplica liberações e bloqueios ─────────────────────────────────
    # IDs que o cargo já permite (descontando bloqueios efetivos)
    ids_por_cargo = set(
        qs_cargo.exclude(id__in=bloqueados_efetivos).values_list("id", flat=True)
    )

    # IDs liberados explicitamente (furam o cargo e ignoram bloqueio)
    ids_finais = ids_por_cargo | liberados

    return User.objects.filter(id__in=ids_finais)


def can_send_to(me, other) -> bool:
    """
    Verifica se 'me' pode enviar mensagem para 'other'.

    Ordem de verificação:
    1. Liberação explícita → sempre permite (fura cargo e bloqueio).
    2. Bloqueio sem liberação → sempre nega (mesmo que o cargo permitisse).
    3. Cargo → segue allowed_contacts.
    """
    if me.is_superuser:
        return True

    if ChatLiberacao.existe(me, other):
        return True

    if ChatBloqueio.existe(me, other):
        return False

    return allowed_contacts(me).filter(id=other.id).exists()


# ==========
# PRESENÇA
# ==========

def _get_presence(user):
    presence, _ = ChatPresence.objects.get_or_create(user=user)
    return presence


def ping_user(user):
    presence = _get_presence(user)
    presence.save(update_fields=["updated_at"])


def effective_status(user) -> str:
    presence = _get_presence(user)

    if presence.status == ChatPresence.Status.OFFLINE:
        return "offline"

    if timezone.now() - presence.updated_at > timedelta(seconds=ONLINE_TTL_SECONDS):
        return "offline"

    if presence.status == ChatPresence.Status.AUSENTE:
        return "ausente"

    return "online"


def is_online(user_id: int) -> bool:
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
    msgs = conv.messages.select_related("sender", "reply_to__sender").prefetch_related("reactions").all()
    return msgs, conv


# ==========
# UNREAD
# ==========

def unread_by_contact(user):
    conv_qs = Conversation.objects.filter(Q(user1=user) | Q(user2=user))
    qs = Message.objects.filter(
        conversation__in=conv_qs,
        lido_em__isnull=True,
    ).exclude(sender=user)
    data = qs.values("sender_id").annotate(c=Count("id"))
    return {row["sender_id"]: row["c"] for row in data}


def unread_count(user) -> int:
    conv_qs = Conversation.objects.filter(Q(user1=user) | Q(user2=user))
    return Message.objects.filter(
        conversation__in=conv_qs,
        lido_em__isnull=True,
    ).exclude(sender=user).count()


def mark_read_conversation(me, other) -> int:
    conv = _get_or_create_conversation(me, other)
    qs = conv.messages.filter(lido_em__isnull=True).exclude(sender=me)
    return qs.update(lido_em=timezone.now())


# ==========
# ENVIO
# ==========

def send_text(me, other, texto: str, imagem=None, reply_to_id=None):
    conv = _get_or_create_conversation(me, other)
    reply_to = None
    if reply_to_id:
        try:
            reply_to = Message.objects.get(id=int(reply_to_id), conversation=conv)
        except (Message.DoesNotExist, ValueError):
            pass
    msg = Message.objects.create(
        conversation=conv,
        sender=me,
        texto=texto or "",
        imagem=imagem if imagem else None,
        reply_to=reply_to,
    )
    return msg


ALLOWED_REACTION_EMOJIS = {"👍", "❤️", "😂", "😮", "😢", "🙏"}


def toggle_reaction(user, message, emoji: str) -> bool:
    if emoji not in ALLOWED_REACTION_EMOJIS:
        return False
    reaction, created = MessageReaction.objects.get_or_create(
        message=message, user=user, emoji=emoji
    )
    if not created:
        reaction.delete()
    return created