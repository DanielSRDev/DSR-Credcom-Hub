from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth import get_user_model

from .services import (
    allowed_contacts,
    can_send_to,
    is_online,
    ping_user,
    unread_by_contact,
    unread_count,
    list_messages_between,
    send_text,
    mark_read_conversation,
)

User = get_user_model()


@login_required
@require_GET
def index(request):
    # Só pra não quebrar reverse('chat_interno:index') caso exista em algum template
    return HttpResponse("ok")


@login_required
@require_POST
def ping(request):
    ping_user(request.user)
    return JsonResponse({"ok": True})


@login_required
@require_GET
def contacts(request):
    user = request.user
    unread_map = unread_by_contact(user)

    items = []
    for u in allowed_contacts(user).order_by("username"):
        items.append(
            {
                "id": u.id,
                "username": u.get_username(),
                "nome": (getattr(u, "get_full_name", lambda: "")() or u.get_username()),
                "online": is_online(u.id),
                "unread": unread_map.get(u.id, 0),
                "can_send": can_send_to(user, u),
            }
        )

    return JsonResponse({"items": items})


@login_required
@require_GET
def unread_total(request):
    return JsonResponse({"count": unread_count(request.user)})


@login_required
@require_GET
def history(request, user_id: int):
    me = request.user
    other = get_object_or_404(User, id=user_id)

    # deixa abrir se "eu posso falar com ele" OU "ele pode falar comigo"
    if not (can_send_to(me, other) or can_send_to(other, me)):
        return JsonResponse({"error": "Sem permissão."}, status=403)

    msgs, conv = list_messages_between(me, other, limit=120)
    mark_read_conversation(me, other)

    return JsonResponse(
        {
            "conversation_id": conv.id,
            "items": [
                {
                    "id": m.id,
                    "sender_id": m.sender_id,
                    "texto": m.texto,
                    "criado_em": m.criado_em.isoformat(),
                    "is_me": m.sender_id == me.id,
                }
                for m in msgs
            ],
        }
    )


@login_required
@require_POST
def send_message(request, user_id: int):
    me = request.user
    other = get_object_or_404(User, id=user_id)

    if not can_send_to(me, other):
        return JsonResponse({"error": "Sem permissão para enviar."}, status=403)

    texto = (request.POST.get("texto") or "").strip()
    if not texto:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)

    msg = send_text(me, other, texto)

    return JsonResponse(
        {
            "ok": True,
            "msg": {
                "id": msg.id,
                "sender_id": msg.sender_id,
                "texto": msg.texto,
                "criado_em": msg.criado_em.isoformat(),
                "is_me": True,
            },
        }
    )


@login_required
@require_POST
def mark_read(request, user_id: int):
    me = request.user
    other = get_object_or_404(User, id=user_id)

    if not (can_send_to(me, other) or can_send_to(other, me)):
        return JsonResponse({"error": "Sem permissão."}, status=403)

    updated = mark_read_conversation(me, other)
    return JsonResponse({"ok": True, "updated": updated})