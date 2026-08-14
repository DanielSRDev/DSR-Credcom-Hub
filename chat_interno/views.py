from __future__ import annotations

import csv
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth import get_user_model

from .models import ChatPresence, ChatMonitorConfig, Message
from .services import (
    allowed_contacts,
    can_send_to,
    can_send_broadcast,
    is_online,
    ping_user,
    unread_by_contact,
    unread_count,
    list_messages_between,
    list_messages_for_range,
    send_text,
    mark_read_conversation,
    effective_status,
    toggle_reaction,
    ALLOWED_REACTION_EMOJIS,
)

User = get_user_model()

HISTORY_PAGE_SIZE = 50


def _serialize_message(m, actor):
    reply_to_data = None
    if m.reply_to_id and m.reply_to:
        rt = m.reply_to
        reply_to_data = {
            "id": rt.id,
            "sender_name": (rt.sender.get_full_name() or rt.sender.get_username() if rt.sender else "?"),
            "texto": (rt.texto or "")[:100],
            "imagem_url": (rt.imagem.url if getattr(rt, "imagem", None) else None),
        }

    reactions = {}
    for r in m.reactions.all():
        if r.emoji not in reactions:
            reactions[r.emoji] = {"count": 0, "mine": False}
        reactions[r.emoji]["count"] += 1
        if r.user_id == actor.id:
            reactions[r.emoji]["mine"] = True

    return {
        "id": m.id,
        "sender_id": m.sender_id,
        "sender_name": (
            m.sender.get_full_name() or m.sender.get_username()
            if m.sender else "Contato"
        ),
        "texto": m.texto or "",
        "imagem_url": (m.imagem.url if getattr(m, "imagem", None) else None),
        "criado_em": m.criado_em.isoformat(),
        "is_me": m.sender_id == actor.id,
        "reply_to": reply_to_data,
        "reactions": reactions,
    }


def can_monitor_chat(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    cfg = getattr(user, "chat_monitor_config", None)
    return bool(cfg and cfg.monitorado)


def get_actor_user(request):
    me = request.user
    as_user = (request.GET.get("as_user") or "").strip()

    if not as_user:
        return me

    if not can_monitor_chat(me):
        return me

    if not as_user.isdigit():
        return me

    try:
        return User.objects.get(id=int(as_user))
    except User.DoesNotExist:
        return me


def can_export_admin(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    from core import roles
    return roles.ve_tudo(user)


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
def my_status(request):
    return JsonResponse({
        "ok": True,
        "status": effective_status(request.user),
    })


@login_required
@require_GET
def contacts(request):
    me = request.user
    actor = get_actor_user(request)

    unread_map = unread_by_contact(actor)

    items = []
    for u in allowed_contacts(actor).order_by("username"):
        items.append(
            {
                "id": u.id,
                "username": u.get_username(),
                "nome": (getattr(u, "get_full_name", lambda: "")() or u.get_username()),
                "unread": unread_map.get(u.id, 0),
                "can_send": can_send_to(actor, u),
                "online": is_online(u.id),
                "status": effective_status(u),
            }
        )

    monitor_users = []
    if can_monitor_chat(me):
        monitor_users = list(
            User.objects.all().order_by("username").values("id", "username")
        )

    return JsonResponse({
        "items": items,
        "can_export": can_export_admin(me),
        "can_broadcast": can_send_broadcast(me),
        "my_status": effective_status(me),
        "can_monitor": can_monitor_chat(me),
        "actor_id": actor.id,
        "monitor_users": monitor_users,
    })


@login_required
@require_GET
def unread_total(request):
    return JsonResponse({"count": unread_count(request.user)})


@login_required
@require_GET
def history(request, user_id: int):
    me = request.user
    actor = get_actor_user(request)
    other = get_object_or_404(User, id=user_id)

    if not (can_send_to(actor, other) or can_send_to(other, actor)):
        return JsonResponse({"error": "Sem permissão."}, status=403)

    def _parse_id(name):
        raw = (request.GET.get(name) or "").strip()
        return int(raw) if raw.isdigit() else None

    after_id = _parse_id("after_id")
    before_id = _parse_id("before_id")

    if after_id is not None:
        msgs, conv, has_more = list_messages_between(actor, other, after_id=after_id)
        items = [_serialize_message(m, actor) for m in msgs]
        return JsonResponse({"items": items, "has_more": has_more})

    date_raw = (request.GET.get("date") or "").strip()
    date_end_raw = (request.GET.get("date_end") or "").strip()

    # Sem before_id (ou com data explícita): carrega o dia/período pedido
    # (padrão hoje), em vez de um lote fixo de mensagens recentes — evita
    # puxar histórico inteiro toda vez que o chat é aberto.
    if date_raw or before_id is None:
        if date_raw:
            try:
                start_day = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except ValueError:
                return JsonResponse({"error": "Data inválida."}, status=400)
        else:
            start_day = timezone.localdate()

        end_day = start_day
        if date_end_raw:
            try:
                end_day = datetime.strptime(date_end_raw, "%Y-%m-%d").date()
            except ValueError:
                return JsonResponse({"error": "Data final inválida."}, status=400)

        msgs, conv, baseline_id = list_messages_for_range(actor, other, start_day, end_day)
        items = [_serialize_message(m, actor) for m in msgs]
        is_today = start_day == end_day == timezone.localdate()
        return JsonResponse({
            "items": items,
            "date": start_day.isoformat(),
            "date_end": end_day.isoformat(),
            "is_today": is_today,
            "baseline_id": baseline_id,
        })

    limit_raw = (request.GET.get("limit") or "").strip()
    limit = int(limit_raw) if limit_raw.isdigit() else HISTORY_PAGE_SIZE
    msgs, conv, has_more = list_messages_between(actor, other, limit=limit, before_id=before_id)
    items = [_serialize_message(m, actor) for m in msgs]
    return JsonResponse({"items": items, "has_more": has_more})


@login_required
@require_POST
def send_message(request, user_id: int):
    me = request.user
    actor = get_actor_user(request)

    if actor.id != me.id:
        return JsonResponse({"error": "Modo monitor: somente visualização."}, status=403)

    other = get_object_or_404(User, id=user_id)

    if not can_send_to(me, other):
        return JsonResponse({"error": "Sem permissão para enviar."}, status=403)

    texto = (request.POST.get("texto") or "").strip()
    imagem = request.FILES.get("imagem")
    reply_to_id = (request.POST.get("reply_to_id") or "").strip() or None

    if not texto and not imagem:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)

    msg = send_text(me, other, texto, imagem=imagem, reply_to_id=reply_to_id)

    return JsonResponse({
        "ok": True,
        "msg": {
            "id": msg.id,
            "sender_id": msg.sender_id,
            "texto": msg.texto or "",
            "imagem_url": (msg.imagem.url if msg.imagem else None),
            "criado_em": msg.criado_em.isoformat(),
            "is_me": True,
        },
    })


@login_required
@require_POST
def mark_read(request, user_id: int):
    me = request.user
    actor = get_actor_user(request)

    if actor.id != me.id:
        return JsonResponse({"ok": True, "updated": 0})

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

    msgs, _, _ = list_messages_between(user1, user2)

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


@login_required
@require_POST
def set_status(request):
    status = request.POST.get("status")

    if status not in ["online", "ausente", "offline"]:
        return JsonResponse({"error": "status inválido"}, status=400)

    presence, _ = ChatPresence.objects.get_or_create(user=request.user)
    presence.status = status
    presence.save()

    # se usuário marcou online/ausente, já atualiza heartbeat na hora
    if status in ["online", "ausente"]:
        ping_user(request.user)

    return JsonResponse({
        "ok": True,
        "status": presence.status
    })


@login_required
@require_POST
def broadcast(request):
    """Envia uma mensagem 1:1 para múltiplos destinatários de uma vez."""
    me = request.user

    if not can_send_broadcast(me):
        return JsonResponse({"error": "Sem permissão para enviar mensagem em massa."}, status=403)

    texto = (request.POST.get("texto") or "").strip()
    user_ids_raw = request.POST.getlist("user_ids[]")

    if not texto:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)
    if not user_ids_raw:
        return JsonResponse({"error": "Nenhum destinatário selecionado."}, status=400)

    sent = 0
    skipped = 0
    for uid_str in user_ids_raw:
        try:
            uid = int(uid_str)
        except (ValueError, TypeError):
            skipped += 1
            continue
        if uid == me.id:
            continue
        try:
            other = User.objects.get(id=uid, is_active=True)
        except User.DoesNotExist:
            skipped += 1
            continue
        if can_send_to(me, other):
            send_text(me, other, texto)
            sent += 1
        else:
            skipped += 1

    return JsonResponse({"ok": True, "sent": sent, "skipped": skipped})


@login_required
@require_POST
def react_message(request, message_id: int):
    me = request.user
    emoji = (request.POST.get("emoji") or "").strip()

    if emoji not in ALLOWED_REACTION_EMOJIS:
        return JsonResponse({"error": "Emoji inválido."}, status=400)

    try:
        msg = Message.objects.select_related("conversation").get(id=message_id)
    except Message.DoesNotExist:
        return JsonResponse({"error": "Mensagem não encontrada."}, status=404)

    conv = msg.conversation
    if me.id not in (conv.user1_id, conv.user2_id) and not me.is_superuser:
        return JsonResponse({"error": "Sem permissão."}, status=403)

    added = toggle_reaction(me, msg, emoji)
    return JsonResponse({"ok": True, "added": added, "emoji": emoji})