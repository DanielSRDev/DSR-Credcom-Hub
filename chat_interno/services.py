from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, List, Optional, Tuple

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.db.models import Q, Count
from django.utils import timezone

from .models import Conversation, Message, ChatVinculoOperador

User = get_user_model()

# ---- Grupos (nomes EXATOS) ----
G_OPERACAO = "OPERACAO"
G_SUPERVISOR = "OPERACAO_SUPERVISOR"
G_CORDENACAO = "OPERACAO_CORDENACAO"

# online: usuário é considerado online se pingou em até X segundos
ONLINE_TTL_SECONDS = 75
ONLINE_KEY_PREFIX = "chat_online_user_"


def _now():
    return timezone.now()


def user_in_group(user, group_name: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists()


def user_role(user) -> str:
    if user.is_superuser:
        return "ADMIN"
    if user_in_group(user, G_CORDENACAO):
        return G_CORDENACAO
    if user_in_group(user, G_SUPERVISOR):
        return G_SUPERVISOR
    if user_in_group(user, G_OPERACAO):
        return G_OPERACAO
    return "OUTRO"


def ensure_order(u1: User, u2: User) -> Tuple[User, User]:
    return (u1, u2) if u1.id < u2.id else (u2, u1)


def get_or_create_conversation(u1: User, u2: User) -> Conversation:
    a, b = ensure_order(u1, u2)
    conv, _ = Conversation.objects.get_or_create(user1=a, user2=b)
    return conv


def mark_online(user: User) -> None:
    key = f"{ONLINE_KEY_PREFIX}{user.id}"
    cache.set(key, _now().isoformat(), timeout=ONLINE_TTL_SECONDS)


def is_online(user_id: int) -> bool:
    return cache.get(f"{ONLINE_KEY_PREFIX}{user_id}") is not None


def unread_count(user: User) -> int:
    """
    Total de mensagens não lidas destinadas ao user (lido_em is null, sender != user).
    """
    if not user.is_authenticated:
        return 0
    return Message.objects.filter(
        conversation__in=Conversation.objects.filter(Q(user1=user) | Q(user2=user)),
        lido_em__isnull=True,
    ).exclude(sender=user).count()


def _supervisor_of_operador(user: User) -> Optional[User]:
    try:
        return user.chat_vinculo_operador.supervisor
    except Exception:
        return None


def _operadores_do_supervisor(user: User) -> List[User]:
    return list(User.objects.filter(chat_vinculo_operador__supervisor=user).distinct())


def _all_coordenacao_users() -> List[User]:
    return list(User.objects.filter(groups__name=G_CORDENACAO, is_active=True).distinct())


def _all_supervisores_users() -> List[User]:
    return list(User.objects.filter(groups__name=G_SUPERVISOR, is_active=True).distinct())


def can_message(sender: User, target: User) -> bool:
    """
    Regras:
    - OPERACAO: só pode iniciar com seu supervisor (vínculo). Pode responder coord/supervisor se já existir conversa.
    - OPERACAO_SUPERVISOR: pode falar com sua equipe + coordenação.
    - OPERACAO_CORDENACAO: pode falar com todos.
    - superuser: pode falar com todos.
    """
    if not sender.is_authenticated or not target.is_active:
        return False
    if sender.id == target.id:
        return False

    if sender.is_superuser:
        return True

    role = user_role(sender)

    if role == G_CORDENACAO:
        return True

    if role == G_SUPERVISOR:
        # pode falar com coordenação
        if user_in_group(target, G_CORDENACAO) or target.is_superuser:
            return True
        # pode falar com operador vinculado a ele
        return ChatVinculoOperador.objects.filter(supervisor=sender, operador=target).exists()

    if role == G_OPERACAO:
        sup = _supervisor_of_operador(sender)
        if sup and sup.id == target.id:
            return True

        # receber de coordenação/supervisor e poder responder SE já existe conversa
        if user_in_group(target, G_CORDENACAO) or user_in_group(target, G_SUPERVISOR) or target.is_superuser:
            a, b = ensure_order(sender, target)
            return Conversation.objects.filter(user1=a, user2=b).exists()

        return False

    # OUTRO: não participa
    return False


def allowed_contacts(user: User) -> List[User]:
    """
    Lista de contatos que aparecem no painel do chat.
    Mantém seu padrão:
    - OPERACAO: vê o supervisor responsável + pessoas que já conversaram com ele (coord/supervisor) (pra não ficar “recebe mas não vê”).
    - SUPERVISOR: vê sua equipe + coordenação.
    - CORDENACAO: vê todos (ativos) que estejam em OPERACAO/SUPERVISOR/CORDENACAO + superusers.
    - ADMIN(superuser): vê todos ativos.
    """
    if not user.is_authenticated:
        return []

    if user.is_superuser:
        return list(User.objects.filter(is_active=True).exclude(id=user.id).order_by("username"))

    role = user_role(user)

    if role == G_CORDENACAO:
        qs = User.objects.filter(is_active=True).exclude(id=user.id).filter(
            Q(groups__name=G_OPERACAO) | Q(groups__name=G_SUPERVISOR) | Q(groups__name=G_CORDENACAO) | Q(is_superuser=True)
        ).distinct().order_by("username")
        return list(qs)

    if role == G_SUPERVISOR:
        contatos = []
        contatos += _operadores_do_supervisor(user)
        contatos += _all_coordenacao_users()
        # remove duplicados e ele mesmo
        uniq = {u.id: u for u in contatos if u.id != user.id and u.is_active}
        return [uniq[k] for k in sorted(uniq.keys(), key=lambda x: (uniq[x].username if hasattr(uniq[x], "username") else str(x)))]

    if role == G_OPERACAO:
        contatos = []
        sup = _supervisor_of_operador(user)
        if sup and sup.is_active and sup.id != user.id:
            contatos.append(sup)

        # adiciona contatos que já possuem conversa com o operador (pra responder coord/sup quando receber)
        convs = Conversation.objects.filter(Q(user1=user) | Q(user2=user))
        other_ids = []
        for c in convs:
            other_ids.append(c.user2_id if c.user1_id == user.id else c.user1_id)
        if other_ids:
            contatos += list(User.objects.filter(id__in=other_ids, is_active=True))

        uniq = {u.id: u for u in contatos if u.id != user.id}
        # ordena por username
        return sorted(uniq.values(), key=lambda u: u.username.lower())

    return []


def contacts_payload(user: User) -> List[dict]:
    """
    Retorna contatos + online + unread por contato.
    """
    contatos = allowed_contacts(user)
    if not contatos:
        return []

    # unread por contato: mensagens não lidas em conversas com aquele contato
    # Faz em Python (simplicidade) - volume pequeno (chat interno).
    payload = []
    for u in contatos:
        conv = None
        a, b = ensure_order(user, u)
        conv = Conversation.objects.filter(user1=a, user2=b).first()
        unread = 0
        last_msg = None
        if conv:
            unread = Message.objects.filter(conversation=conv, lido_em__isnull=True).exclude(sender=user).count()
            last_msg = Message.objects.filter(conversation=conv).order_by("-criado_em").first()

        payload.append({
            "id": u.id,
            "username": u.username,
            "nome": getattr(u, "get_full_name", lambda: "")() or u.username,
            "online": is_online(u.id),
            "unread": unread,
            "last": (last_msg.texto[:60] if last_msg else ""),
            "last_at": (last_msg.criado_em.isoformat() if last_msg else None),
        })

    # ordena: quem tem msg recente primeiro, depois username
    def sort_key(x):
        return (x["last_at"] is None, x["last_at"] or "", x["username"].lower())

    payload.sort(key=sort_key)
    return payload


def fetch_messages(user: User, other_id: int, limit: int = 80) -> List[dict]:
    other = User.objects.filter(id=other_id, is_active=True).first()
    if not other:
        return []

    # só deixa ver se ele tem permissão de conversar (ou já existe conversa e é reply permitido)
    if not can_message(user, other) and not can_message(other, user):
        return []

    conv = get_or_create_conversation(user, other)

    qs = Message.objects.filter(conversation=conv).order_by("-criado_em")[:limit]
    msgs = list(reversed(qs))

    # marca como lidas as mensagens recebidas
    Message.objects.filter(conversation=conv, lido_em__isnull=True).exclude(sender=user).update(lido_em=_now())

    out = []
    for m in msgs:
        out.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "author": m.sender.username,
            "text": m.texto,
            "created_at": m.criado_em.isoformat(),
            "mine": (m.sender_id == user.id),
        })
    return out


def send_message(user: User, other_id: int, text: str) -> dict:
    other = User.objects.filter(id=other_id, is_active=True).first()
    if not other:
        return {"ok": False, "error": "Contato inválido."}

    if not can_message(user, other):
        return {"ok": False, "error": "Sem permissão para enviar mensagem para este contato."}

    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Mensagem vazia."}
    if len(text) > 4000:
        return {"ok": False, "error": "Mensagem muito grande."}

    conv = get_or_create_conversation(user, other)
    m = Message.objects.create(conversation=conv, sender=user, texto=text)

    return {
        "ok": True,
        "message": {
            "id": m.id,
            "sender_id": m.sender_id,
            "author": user.username,
            "text": m.texto,
            "created_at": m.criado_em.isoformat(),
            "mine": True,
        }
    }


def search_history(user: User, other_id: int, q: str, limit: int = 50) -> List[dict]:
    other = User.objects.filter(id=other_id, is_active=True).first()
    if not other:
        return []
    if not can_message(user, other) and not can_message(other, user):
        return []

    conv = get_or_create_conversation(user, other)
    q = (q or "").strip()
    if not q:
        return []

    qs = Message.objects.filter(conversation=conv, texto__icontains=q).order_by("-criado_em")[:limit]
    out = []
    for m in qs:
        out.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "author": m.sender.username,
            "text": m.texto,
            "created_at": m.criado_em.isoformat(),
            "mine": (m.sender_id == user.id),
        })
    return out