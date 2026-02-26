import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.http import require_GET, require_POST

from .services import (
    mark_online,
    contacts_payload,
    fetch_messages,
    send_message,
    search_history,
)


@login_required
@require_POST
def ping(request):
    """
    Front chama regularmente pra manter online.
    """
    mark_online(request.user)
    return JsonResponse({"ok": True})


@login_required
@require_GET
def contacts(request):
    """
    Lista contatos permitidos + online + unread.
    """
    mark_online(request.user)
    return JsonResponse({"ok": True, "contacts": contacts_payload(request.user)})


@login_required
@require_GET
def messages(request, other_id: int):
    """
    Carrega mensagens com um contato.
    """
    mark_online(request.user)
    msgs = fetch_messages(request.user, other_id=other_id, limit=120)
    return JsonResponse({"ok": True, "messages": msgs})


@login_required
@require_POST
def send(request, other_id: int):
    """
    Envia mensagem.
    """
    mark_online(request.user)

    # aceita form-data (text) ou JSON
    text = request.POST.get("text", "")
    if not text:
        try:
            data = json.loads(request.body.decode("utf-8") or "{}")
            text = data.get("text", "")
        except Exception:
            text = ""

    resp = send_message(request.user, other_id=other_id, text=text)
    return JsonResponse(resp)


@login_required
@require_GET
def search(request, other_id: int):
    """
    Pesquisa no histórico com o contato (texto__icontains).
    """
    mark_online(request.user)
    q = request.GET.get("q", "")
    found = search_history(request.user, other_id=other_id, q=q, limit=60)
    return JsonResponse({"ok": True, "results": found})