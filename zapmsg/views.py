import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import ZapConta, ZapConversa, ZapMensagem
from .permissions import resolve_target_user, serialize_allowed_targets
from .services import (
    ZapConnectorError,
    disconnect_session,
    get_or_create_conta,
    get_or_create_contact_and_conversation,
    get_session_status,
    register_incoming_message,
    register_outgoing_message,
    resolve_contact_wa_id,
    send_media_message,
    send_message,
    start_session,
    sync_conta_with_connector,
    update_message_ack,
)

logger = logging.getLogger(__name__)


def _get_target_conta(request):
    target_user = resolve_target_user(request)
    conta = get_or_create_conta(target_user)
    return target_user, conta


def _is_valid_real_contact(wa_id: str) -> bool:
    wa_id = (wa_id or "").strip().lower()

    if not wa_id:
        return False

    if wa_id == "status@broadcast":
        return False

    if wa_id.endswith("@broadcast"):
        return False

    if wa_id.endswith("@g.us"):
        return False

    if wa_id.endswith("@newsletter"):
        return False

    if wa_id.endswith("@call"):
        return False

    return True


@login_required
def dashboard(request):
    target_user, conta = _get_target_conta(request)
    monitor_data = serialize_allowed_targets(request.user)

    return render(request, "zapmsg/dashboard.html", {
        "conta": conta,
        "target_user": target_user,
        "monitor_targets": monitor_data["targets"],
        "can_monitor_all": monitor_data["can_monitor_all"],
    })


@login_required
def api_targets(request):
    target_user, _ = _get_target_conta(request)
    data = serialize_allowed_targets(request.user)

    return JsonResponse({
        "ok": True,
        "current_target_id": target_user.id,
        "current_target_username": target_user.username,
        "targets": data["targets"],
        "can_monitor_all": data["can_monitor_all"],
    })


@login_required
def iniciar_conexao(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Método inválido"}, status=405)

    _, conta = _get_target_conta(request)

    try:
        conta.status = ZapConta.Status.CONECTANDO
        conta.ultimo_erro = ""
        conta.qr_code = ""
        conta.save(update_fields=["status", "ultimo_erro", "qr_code", "atualizado_em"])

        data = start_session(conta.session_id, force_new=False)
        sync_conta_with_connector(conta, data)

        return JsonResponse({"ok": True, "data": data})
    except ZapConnectorError as e:
        conta.status = ZapConta.Status.ERRO
        conta.ultimo_erro = str(e)
        conta.save(update_fields=["status", "ultimo_erro", "atualizado_em"])
        return JsonResponse({"ok": False, "erro": str(e)}, status=500)


@login_required
def status_conexao(request):
    target_user, conta = _get_target_conta(request)

    try:
        connector_data = get_session_status(conta.session_id)
        sync_conta_with_connector(conta, connector_data)
    except ZapConnectorError:
        connector_data = {}

    return JsonResponse({
        "ok": True,
        "target_user_id": target_user.id,
        "target_username": target_user.username,
        "status": conta.status,
        "nome_perfil": conta.nome_perfil,
        "telefone": conta.telefone,
        "qr_code": conta.qr_code,
        "ultimo_erro": conta.ultimo_erro,
        "connected": conta.status == ZapConta.Status.CONECTADO,
        "conectado": conta.status == ZapConta.Status.CONECTADO,
        "connector": connector_data,
    })


@login_required
def desconectar(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Método inválido"}, status=405)

    _, conta = _get_target_conta(request)

    try:
        data = disconnect_session(conta.session_id)

        conta.status = ZapConta.Status.DESCONECTADO
        conta.nome_perfil = ""
        conta.telefone = ""
        conta.qr_code = ""
        conta.ultimo_erro = ""
        conta.save(update_fields=[
            "status", "nome_perfil", "telefone", "qr_code",
            "ultimo_erro", "atualizado_em"
        ])

        return JsonResponse({"ok": True, "data": data})
    except ZapConnectorError as e:
        return JsonResponse({"ok": False, "erro": str(e)}, status=500)


@login_required
def api_conversas(request):
    _, conta = _get_target_conta(request)

    conversas = (
        ZapConversa.objects
        .select_related("contato")
        .filter(conta=conta, arquivada=False)
        .order_by("-fixada", "-ultima_mensagem_em", "-id")
    )

    data = []
    for c in conversas:
        wa_id = (c.contato.wa_id or "").strip()

        if not _is_valid_real_contact(wa_id):
            continue

        data.append({
            "id": c.id,
            "contato_id": c.contato.id,
            "nome": c.contato.display_name,
            "numero": c.contato.numero,
            "wa_id": c.contato.wa_id,
            "ultima_mensagem": c.ultima_mensagem or "",
            "ultima_mensagem_em": c.ultima_mensagem_em.strftime("%d/%m/%Y %H:%M") if c.ultima_mensagem_em else "",
            "nao_lidas": c.nao_lidas,
            "fixada": c.fixada,
            "status_atendimento": c.status_atendimento,
        })

    return JsonResponse({"ok": True, "conversas": data})


@login_required
def api_mensagens_conversa(request, conversa_id):
    _, conta = _get_target_conta(request)

    conversa = get_object_or_404(
        ZapConversa.objects.select_related("contato"),
        id=conversa_id,
        conta=conta,
    )

    if not _is_valid_real_contact(conversa.contato.wa_id):
        return JsonResponse({"ok": False, "erro": "Conversa inválida"}, status=404)

    mensagens = conversa.mensagens.order_by("enviada_em", "id")

    data = []
    for m in mensagens:
        raw = m.raw_payload or {}
        data.append({
            "id": m.id,
            "externo_id": m.externo_id,
            "direction": m.direction,
            "tipo": m.tipo,
            "status_envio": m.status_envio,
            "texto": m.texto or "",
            "media_url": m.media_url or "",
            "filename": raw.get("filename", "") or raw.get("fileName", "") or "",
            "mimetype": raw.get("mimetype", "") or "",
            "enviada_em": m.enviada_em.strftime("%d/%m/%Y %H:%M"),
            "lida": m.lida,
        })

    return JsonResponse({
        "ok": True,
        "conversa": {
            "id": conversa.id,
            "nome": conversa.contato.display_name,
            "numero": conversa.contato.numero,
            "wa_id": conversa.contato.wa_id,
            "nao_lidas": conversa.nao_lidas,
        },
        "mensagens": data,
    })


@login_required
def api_enviar_mensagem_conversa(request, conversa_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Método inválido"}, status=405)

    _, conta = _get_target_conta(request)

    conversa = get_object_or_404(
        ZapConversa.objects.select_related("contato"),
        id=conversa_id,
        conta=conta,
    )

    if not _is_valid_real_contact(conversa.contato.wa_id):
        return JsonResponse({"ok": False, "erro": "Conversa inválida"}, status=400)

    texto = (request.POST.get("texto") or "").strip()
    arquivo = request.FILES.get("arquivo")

    if not texto and not arquivo:
        return JsonResponse({"ok": False, "erro": "Mensagem vazia"}, status=400)

    if conta.status != ZapConta.Status.CONECTADO:
        return JsonResponse({"ok": False, "erro": "Conta não está conectada"}, status=400)

    try:
        if arquivo:
            data = send_media_message(
                conta.session_id,
                conversa.contato.numero,
                arquivo,
                wa_id=conversa.contato.wa_id,
                caption=texto,
            )
            msg, _ = register_outgoing_message(
                conta=conta,
                number=conversa.contato.numero,
                texto=texto,
                externo_id=data.get("message_id", ""),
                raw_payload=data,
                wa_id=data.get("to") or conversa.contato.wa_id,
                tipo=data.get("tipo") or "arquivo",
                media_url=data.get("media_data_url", "") or "",
            )
        else:
            data = send_message(
                conta.session_id,
                conversa.contato.numero,
                texto,
                wa_id=conversa.contato.wa_id,
            )
            msg, _ = register_outgoing_message(
                conta=conta,
                number=conversa.contato.numero,
                texto=texto,
                externo_id=data.get("message_id", ""),
                raw_payload=data,
                wa_id=data.get("to") or conversa.contato.wa_id,
            )

        return JsonResponse({
            "ok": True,
            "mensagem": {
                "id": msg.id,
                "texto": msg.texto,
                "direction": msg.direction,
                "tipo": msg.tipo,
                "status_envio": msg.status_envio,
                "enviada_em": msg.enviada_em.strftime("%d/%m/%Y %H:%M"),
            }
        })
    except ZapConnectorError as e:
        logger.exception("Erro ao enviar mensagem | conversa_id=%s", conversa.id)
        return JsonResponse({
            "ok": False,
            "erro": str(e),
            "detalhe": "Falha no connector ao tentar enviar a mensagem."
        }, status=500)

    except Exception as e:
        logger.exception("Erro interno ao registrar envio | conversa_id=%s", conversa.id)
        return JsonResponse({
            "ok": False,
            "erro": str(e),
            "detalhe": e.__class__.__name__,
        }, status=500)


@login_required
def api_marcar_conversa_lida(request, conversa_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Método inválido"}, status=405)

    _, conta = _get_target_conta(request)
    conversa = get_object_or_404(ZapConversa, id=conversa_id, conta=conta)

    conversa.nao_lidas = 0
    conversa.save(update_fields=["nao_lidas", "atualizado_em"])

    conversa.mensagens.filter(
        direction=ZapMensagem.Direction.IN,
        lida=False,
    ).update(lida=True, atualizado_em=timezone.now())

    return JsonResponse({"ok": True})


@login_required
def api_nova_conversa(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Método inválido"}, status=405)

    _, conta = _get_target_conta(request)
    numero = (request.POST.get("numero") or "").strip()
    nome = (request.POST.get("nome") or "").strip()

    if not numero:
        return JsonResponse({"ok": False, "erro": "Número é obrigatório"}, status=400)

    contato, conversa = get_or_create_contact_and_conversation(
        conta=conta,
        wa_id=numero,
        nome=nome,
        contact_number=numero,
    )

    return JsonResponse({
        "ok": True,
        "conversa": {
            "id": conversa.id,
            "nome": contato.display_name,
            "numero": contato.numero,
            "wa_id": contato.wa_id,
        }
    })


@login_required
def api_excluir_conversa(request, conversa_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Método inválido"}, status=405)

    _, conta = _get_target_conta(request)
    conversa = get_object_or_404(ZapConversa, id=conversa_id, conta=conta)
    contato = conversa.contato

    conversa.mensagens.all().delete()
    conversa.delete()

    if not ZapConversa.objects.filter(conta=conta, contato=contato).exists():
        contato.delete()

    return JsonResponse({"ok": True})


@csrf_exempt
def webhook_evento(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Método inválido"}, status=405)

    token = request.headers.get("X-Zapmsg-Token", "")
    expected = getattr(settings, "ZAPMSG_WEBHOOK_TOKEN", "")

    if not expected or token != expected:
        return HttpResponseForbidden("Webhook token inválido")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "erro": "JSON inválido"}, status=400)

    session_id = payload.get("session_id")
    event = payload.get("event")
    data = payload.get("data", {}) or {}

    if not session_id:
        return JsonResponse({"ok": False, "erro": "session_id obrigatório"}, status=400)

    try:
        conta = ZapConta.objects.get(session_id=session_id)
    except ZapConta.DoesNotExist:
        return JsonResponse({"ok": False, "erro": "Conta não encontrada"}, status=404)

    conta.ultimo_ping = timezone.now()

    try:
        if event == "qr":
            conta.status = ZapConta.Status.AGUARDANDO_QR
            conta.qr_code = data.get("qr_image", "")
            conta.ultimo_erro = ""
            conta.save(update_fields=["status", "qr_code", "ultimo_erro", "ultimo_ping", "atualizado_em"])

        elif event == "ready":
            conta.status = ZapConta.Status.CONECTADO
            conta.nome_perfil = data.get("pushname", "") or data.get("name", "")
            conta.telefone = data.get("phone", "")
            conta.qr_code = ""
            conta.conectado_em = timezone.now()
            conta.ultimo_erro = ""
            conta.save(update_fields=[
                "status", "nome_perfil", "telefone", "qr_code",
                "conectado_em", "ultimo_erro", "ultimo_ping", "atualizado_em"
            ])

        elif event == "disconnected":
            conta.status = ZapConta.Status.DESCONECTADO
            conta.qr_code = ""
            conta.nome_perfil = ""
            conta.telefone = ""
            conta.save(update_fields=[
                "status", "qr_code", "nome_perfil", "telefone",
                "ultimo_ping", "atualizado_em"
            ])

        elif event == "auth_failure":
            conta.status = ZapConta.Status.ERRO
            conta.ultimo_erro = data.get("message", "Falha de autenticação")
            conta.save(update_fields=["status", "ultimo_erro", "ultimo_ping", "atualizado_em"])

        elif event == "message":
            logger.info("Webhook message recebido | session=%s | data=%s", session_id, data)

            wa_id_contato = resolve_contact_wa_id(conta, data)
            if not wa_id_contato:
                return JsonResponse({"ok": False, "erro": "wa_id do contato não resolvido"}, status=400)

            if not _is_valid_real_contact(wa_id_contato):
                return JsonResponse({"ok": True, "ignored": True})

            contact_number = data.get("contact_number") or ""

            msg, created = register_incoming_message(
                conta=conta,
                wa_id=wa_id_contato,
                texto=data.get("body", ""),
                externo_id=data.get("id", ""),
                nome=data.get("name", ""),
                contact_number=contact_number,
                raw_payload=data,
                tipo=data.get("tipo") or data.get("type") or "texto",
                media_url=data.get("media_data_url", "") or data.get("media_url", "") or "",
            )

            logger.info(
                "Mensagem salva | msg_id=%s | created=%s | conversa_id=%s | wa_id=%s",
                msg.id,
                created,
                msg.conversa_id,
                wa_id_contato,
            )

            conta.save(update_fields=["ultimo_ping", "atualizado_em"])

        elif event == "message_ack":
            msg = update_message_ack(
                conta=conta,
                externo_id=data.get("id", ""),
                ack=data.get("ack"),
                raw_payload=data,
            )

            logger.info(
                "ACK processado | session=%s | externo_id=%s | msg_id=%s | ack=%s",
                session_id,
                data.get("id", ""),
                getattr(msg, "id", None),
                data.get("ack"),
            )

            conta.save(update_fields=["ultimo_ping", "atualizado_em"])

        else:
            logger.info("Evento ignorado | session=%s | event=%s | data=%s", session_id, event, data)
            conta.save(update_fields=["ultimo_ping", "atualizado_em"])

        return JsonResponse({"ok": True})

    except Exception as e:
        logger.exception("Erro no webhook_evento | session=%s | event=%s", session_id, event)
        return JsonResponse({"ok": False, "erro": str(e)}, status=500)


@login_required
def api_enviar_arquivo_conversa(request, conversa_id):
    return api_enviar_mensagem_conversa(request, conversa_id)