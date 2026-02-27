from __future__ import annotations

import csv
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


def can_export_admin(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    # Coordenação
    return user.groups.filter(name="OPERACAO_CORDENACAO").exists()


@login_required
@require_GET
def index(request):
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

    return JsonResponse({"items": items, "can_export": can_export_admin(user)})


@login_required
@require_GET
def unread_total(request):
    return JsonResponse({"count": unread_count(request.user)})


@login_required
@require_GET
def history(request, user_id: int):
    me = request.user
    other = get_object_or_404(User, id=user_id)

    if not (can_send_to(me, other) or can_send_to(other, me)):
        return JsonResponse({"error": "Sem permissão."}, status=403)

    msgs, conv = list_messages_between(me, other)

    items = []
    for m in msgs:
        items.append(
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "texto": m.texto or "",
                "imagem_url": (m.imagem.url if getattr(m, "imagem", None) else None),
                "criado_em": m.criado_em.isoformat(),
                "is_me": m.sender_id == me.id,
            }
        )

    return JsonResponse({"items": items})


@login_required
@require_POST
def send_message(request, user_id: int):
    me = request.user
    other = get_object_or_404(User, id=user_id)

    if not can_send_to(me, other):
        return JsonResponse({"error": "Sem permissão para enviar."}, status=403)

    texto = (request.POST.get("texto") or "").strip()
    imagem = request.FILES.get("imagem")

    if not texto and not imagem:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)

    msg = send_text(me, other, texto, imagem=imagem)

    return JsonResponse(
        {
            "ok": True,
            "msg": {
                "id": msg.id,
                "sender_id": msg.sender_id,
                "texto": msg.texto or "",
                "imagem_url": (msg.imagem.url if msg.imagem else None),
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


@login_required
@require_GET
def export_history(request):
    if not can_export_admin(request.user):
        return JsonResponse({"error": "Sem permissão para exportar."}, status=403)

    # admin passa ids OU usernames: ?u1=ID|username&u2=ID|username
    u1_raw = (request.GET.get("u1") or "").strip()
    u2_raw = (request.GET.get("u2") or "").strip()
    if not u1_raw or not u2_raw:
        return JsonResponse({"error": "Informe u1 e u2."}, status=400)

    def get_user(val: str):
        if val.isdigit():
            return get_object_or_404(User, id=int(val))
        return get_object_or_404(User, username__iexact=val)

    user1 = get_user(u1_raw)
    user2 = get_user(u2_raw)

    msgs, _ = list_messages_between(user1, user2)

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="chat_{user1.id}_{user2.id}.csv"'

    w = csv.writer(resp, delimiter=";")
    w.writerow(["criado_em", "sender", "texto", "imagem_url"])

    for m in msgs:
        w.writerow([
            m.criado_em.isoformat(),
            m.sender.get_username(),
            (m.texto or "").replace("\n", " "),
            (m.imagem.url if getattr(m, "imagem", None) else ""),
        ])

    return resp