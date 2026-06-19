from datetime import datetime
import base64
import mimetypes
import requests
from django.conf import settings
from django.utils import timezone

from .models import ZapConta, ZapContato, ZapConversa, ZapMensagem


class ZapConnectorError(Exception):
    pass


def _base_url():
    return getattr(settings, "ZAPMSG_CONNECTOR_URL", "http://127.0.0.1:3010").rstrip("/")


def _timeout():
    return 60


def start_session(session_id: str, force_new: bool = False):
    r = requests.post(
        f"{_base_url()}/session/start",
        json={"session_id": session_id, "force_new": force_new},
        timeout=_timeout(),
    )
    if not r.ok:
        raise ZapConnectorError(f"Erro start_session: {r.text}")
    return r.json()


def get_session_status(session_id: str):
    r = requests.get(f"{_base_url()}/session/status/{session_id}", timeout=_timeout())
    if not r.ok:
        raise ZapConnectorError(f"Erro get_session_status: {r.text}")
    return r.json()


def disconnect_session(session_id: str):
    r = requests.post(f"{_base_url()}/session/disconnect/{session_id}", timeout=_timeout())
    if not r.ok:
        raise ZapConnectorError(f"Erro disconnect_session: {r.text}")
    return r.json()


def send_message(session_id: str, number: str, text: str, wa_id: str = ""):
    r = requests.post(
        f"{_base_url()}/message/send",
        json={
            "session_id": session_id,
            "number": number,
            "text": text,
            "wa_id": wa_id or "",
        },
        timeout=_timeout(),
    )
    if not r.ok:
        raise ZapConnectorError(f"Erro send_message: {r.text}")
    return r.json()


def send_media_message(session_id: str, number: str, uploaded_file, wa_id: str = "", caption: str = ""):
    content = uploaded_file.read()
    payload = {
        "session_id": session_id,
        "number": number,
        "wa_id": wa_id or "",
        "caption": caption or "",
        "filename": uploaded_file.name,
        "mimetype": getattr(uploaded_file, "content_type", "") or mimetypes.guess_type(uploaded_file.name)[0] or "application/octet-stream",
        "base64": base64.b64encode(content).decode("utf-8"),
    }
    r = requests.post(
        f"{_base_url()}/message/send-media",
        json=payload,
        timeout=180,
    )
    if not r.ok:
        raise ZapConnectorError(f"Erro send_media_message: {r.text}")
    return r.json()


def only_digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def is_lid(wa_id: str) -> bool:
    return str(wa_id or "").lower().endswith("@lid")


def is_phone_jid(wa_id: str) -> bool:
    return str(wa_id or "").lower().endswith("@c.us")


def normalize_wa_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""

    if "@" in value:
        return value.lower()

    digits = only_digits(value)
    if not digits:
        return ""

    if digits.startswith("55"):
        base = digits[2:]
    else:
        base = digits

    if len(base) not in (10, 11):
        return ""

    return f"55{base}@c.us"


def extract_number_from_wa_id(wa_id: str) -> str:
    wa_id = (wa_id or "").strip().lower()
    if not wa_id:
        return ""

    local = wa_id.split("@")[0] if "@" in wa_id else wa_id
    return only_digits(local)


def normalize_phone_compare(value: str) -> str:
    digits = only_digits(value)
    if not digits:
        return ""

    if digits.startswith("55"):
        digits = digits[2:]

    if len(digits) > 11:
        digits = digits[-11:]

    return digits


def phone_variants(value: str) -> set[str]:
    digits = normalize_phone_compare(value)
    if not digits:
        return set()

    variants = {digits}

    if len(digits) == 11 and digits[2] == "9":
        variants.add(digits[:2] + digits[3:])

    if len(digits) == 10:
        variants.add(digits[:2] + "9" + digits[2:])

    return variants


def same_phone(a: str, b: str) -> bool:
    va = phone_variants(a)
    vb = phone_variants(b)
    if not va or not vb:
        return False
    return bool(va.intersection(vb))


def is_real_phone_number(value: str) -> bool:
    digits = only_digits(value)
    if not digits:
        return False

    if digits.startswith("55"):
        base = digits[2:]
    else:
        base = digits

    return len(base) in (10, 11)


def get_or_create_conta(user):
    conta, _ = ZapConta.objects.get_or_create(user=user)
    return conta


def sync_conta_with_connector(conta: ZapConta, connector_data: dict):
    if not connector_data:
        return conta

    changed = []

    connector_status = connector_data.get("status") or ""
    qr_image = connector_data.get("qr_image") or ""
    phone = connector_data.get("phone") or ""
    pushname = connector_data.get("pushname") or ""
    error = connector_data.get("error") or ""

    if connector_status and conta.status != connector_status:
        conta.status = connector_status
        changed.append("status")

    if conta.qr_code != qr_image:
        conta.qr_code = qr_image
        changed.append("qr_code")

    if conta.telefone != phone:
        conta.telefone = phone
        changed.append("telefone")

    if conta.nome_perfil != pushname:
        conta.nome_perfil = pushname
        changed.append("nome_perfil")

    if conta.ultimo_erro != error:
        conta.ultimo_erro = error
        changed.append("ultimo_erro")

    conta.ultimo_ping = timezone.now()
    changed.append("ultimo_ping")

    if connector_status == ZapConta.Status.CONECTADO and not conta.conectado_em:
        conta.conectado_em = timezone.now()
        changed.append("conectado_em")

    if changed:
        changed.append("atualizado_em")
        conta.save(update_fields=list(dict.fromkeys(changed)))

    return conta


def resolve_contact_wa_id(conta: ZapConta, data: dict) -> str:
    candidates = [
        normalize_wa_id(data.get("contact_wa_id", "")),
        normalize_wa_id(data.get("from", "")),
        normalize_wa_id(data.get("chat_id", "")),
        normalize_wa_id(data.get("to", "")),
    ]

    own_wa = normalize_wa_id(data.get("self_wa_id", "")) or normalize_wa_id(conta.telefone)
    own_number = extract_number_from_wa_id(own_wa) or only_digits(conta.telefone)

    for candidate in candidates:
        if not candidate:
            continue
        if own_wa and candidate == own_wa:
            continue
        if is_phone_jid(candidate):
            cand_number = extract_number_from_wa_id(candidate)
            if cand_number and own_number and same_phone(cand_number, own_number):
                continue
        return candidate
    return ""


def _find_contact_by_exact_wa_id(conta: ZapConta, wa_id: str):
    if not wa_id:
        return None
    return ZapContato.objects.filter(conta=conta, wa_id=wa_id).first()


def _find_contact_by_phone(conta: ZapConta, number: str):
    if not number or not is_real_phone_number(number):
        return None
    candidatos = []
    for c in ZapContato.objects.filter(conta=conta):
        c_numero = c.numero or extract_number_from_wa_id(c.wa_id)
        if c_numero and is_real_phone_number(c_numero) and same_phone(c_numero, number):
            candidatos.append(c)
    if len(candidatos) == 1:
        return candidatos[0]
    return None


def _find_existing_contact(conta: ZapConta, wa_id: str, contact_number: str = ""):
    wa_id = normalize_wa_id(wa_id)
    if not wa_id:
        return None
    contato = _find_contact_by_exact_wa_id(conta, wa_id)
    if contato:
        return contato
    if is_phone_jid(wa_id):
        numero = extract_number_from_wa_id(wa_id)
        contato = _find_contact_by_phone(conta, numero)
        if contato:
            return contato
    if is_lid(wa_id) and contact_number and is_real_phone_number(contact_number):
        contato = _find_contact_by_phone(conta, contact_number)
        if contato:
            return contato
    return None


def get_or_create_contact_and_conversation(conta: ZapConta, wa_id: str, nome: str = "", contact_number: str = ""):
    wa_id = normalize_wa_id(wa_id)
    numero_extraido = extract_number_from_wa_id(wa_id)
    numero_real = ""

    if is_real_phone_number(contact_number):
        numero_real = only_digits(contact_number)
    elif is_real_phone_number(numero_extraido):
        numero_real = numero_extraido

    contato = _find_existing_contact(conta, wa_id, contact_number=numero_real)
    if not contato:
        contato = ZapContato.objects.create(
            conta=conta,
            wa_id=wa_id,
            numero=numero_real,
            nome=nome or "",
            nome_exibicao=nome or numero_real or wa_id,
            ultima_interacao_em=timezone.now(),
        )
    else:
        changed = False
        current_is_phone = is_phone_jid(contato.wa_id)
        incoming_is_phone = is_phone_jid(wa_id)
        if wa_id:
            if not current_is_phone and incoming_is_phone and contato.wa_id != wa_id:
                contato.wa_id = wa_id
                changed = True
            elif not contato.wa_id:
                contato.wa_id = wa_id
                changed = True
        if numero_real and contato.numero != numero_real:
            contato.numero = numero_real
            changed = True
        if nome and contato.nome != nome:
            contato.nome = nome
            changed = True
        if nome and (not contato.nome_exibicao or contato.nome_exibicao in {contato.numero, contato.wa_id, ""}):
            contato.nome_exibicao = nome
            changed = True
        contato.ultima_interacao_em = timezone.now()
        changed = True
        if changed:
            contato.save()

    conversa = ZapConversa.objects.filter(conta=conta, contato=contato).first()
    if not conversa:
        conversa = ZapConversa.objects.create(conta=conta, contato=contato, ultima_mensagem_em=timezone.now())
    return contato, conversa


def _message_label(tipo: str, texto: str = "", filename: str = ""):
    if texto:
        return texto
    labels = {
        ZapMensagem.Tipo.AUDIO: "🎵 Áudio",
        ZapMensagem.Tipo.IMAGEM: "📷 Imagem",
        ZapMensagem.Tipo.DOCUMENTO: f"📄 {filename or 'Documento'}",
        ZapMensagem.Tipo.VIDEO: "🎬 Vídeo",
        ZapMensagem.Tipo.ARQUIVO: f"📎 {filename or 'Arquivo'}",
    }
    return labels.get(tipo, "")


def _normalize_tipo(tipo: str, mimetype: str = "", filename: str = ""):
    tipo = str(tipo or "").strip().lower()
    mime = str(mimetype or "").lower()
    name = str(filename or "").lower()
    if tipo in {"audio", "ptt", "voice"} or mime.startswith("audio/"):
        return ZapMensagem.Tipo.AUDIO
    if tipo in {"image", "imagem"} or mime.startswith("image/"):
        return ZapMensagem.Tipo.IMAGEM
    if tipo in {"video", "video_note"} or mime.startswith("video/"):
        return ZapMensagem.Tipo.VIDEO
    if tipo in {"document", "documento"}:
        return ZapMensagem.Tipo.DOCUMENTO
    if name.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".zip")):
        return ZapMensagem.Tipo.DOCUMENTO
    if mime and mime != "application/octet-stream":
        return ZapMensagem.Tipo.ARQUIVO
    return ZapMensagem.Tipo.TEXTO


def register_incoming_message(conta, wa_id, texto, externo_id="", nome="", contact_number="", raw_payload=None, tipo="texto", media_url=""):
    wa_id = normalize_wa_id(wa_id)
    if not wa_id:
        raise ValueError("wa_id inválido para mensagem recebida")
    contato, conversa = get_or_create_contact_and_conversation(conta=conta, wa_id=wa_id, nome=nome, contact_number=contact_number)
    if externo_id:
        existente = ZapMensagem.objects.filter(conversa=conversa, externo_id=externo_id).first()
        if existente:
            return existente, False
    payload = raw_payload or {}
    ts = payload.get("timestamp")
    enviada_em = timezone.now()
    if ts:
        try:
            enviada_em = datetime.fromtimestamp(int(ts), tz=timezone.get_current_timezone())
        except Exception:
            enviada_em = timezone.now()
    final_tipo = _normalize_tipo(tipo, payload.get("mimetype", ""), payload.get("filename", ""))
    msg = ZapMensagem.objects.create(
        conversa=conversa,
        externo_id=externo_id or "",
        direction=ZapMensagem.Direction.IN,
        tipo=final_tipo,
        status_envio=ZapMensagem.StatusEnvio.RECEBIDA,
        texto=texto or "",
        media_url=media_url or payload.get("media_url", "") or payload.get("media_data_url", "") or "",
        raw_payload=payload,
        enviada_em=enviada_em,
        lida=False,
    )
    conversa.atualizar_ultima_interacao(texto=_message_label(final_tipo, texto or "", payload.get("filename", "")), data=msg.enviada_em, incrementar_nao_lidas=True)
    return msg, True


def register_outgoing_message(conta, number, texto, externo_id="", raw_payload=None, wa_id="", tipo="texto", media_url="", conversa=None):
    # Quando a conversa de origem e conhecida (envio a partir do chat aberto),
    # registramos a mensagem DIRETAMENTE nela, sem re-resolver o contato. Isso
    # impede que uma resposta enviada na conversa X seja gravada na conversa Y
    # por causa do match aproximado de telefone.
    if conversa is not None:
        contato = conversa.contato
    else:
        target_wa_id = normalize_wa_id(wa_id) or normalize_wa_id(number)
        contato, conversa = get_or_create_contact_and_conversation(conta=conta, wa_id=target_wa_id, nome="", contact_number=number)
    if externo_id:
        existente = ZapMensagem.objects.filter(conversa=conversa, externo_id=externo_id).first()
        if existente:
            return existente, False
    payload = raw_payload or {}
    final_tipo = _normalize_tipo(tipo, payload.get("mimetype", ""), payload.get("filename", ""))
    msg = ZapMensagem.objects.create(
        conversa=conversa,
        externo_id=externo_id or "",
        direction=ZapMensagem.Direction.OUT,
        tipo=final_tipo,
        status_envio=ZapMensagem.StatusEnvio.ENVIADA,
        texto=texto or "",
        media_url=media_url or payload.get("media_url", "") or payload.get("media_data_url", "") or "",
        raw_payload=payload,
        enviada_em=timezone.now(),
        lida=False,
    )
    conversa.atualizar_ultima_interacao(texto=_message_label(final_tipo, texto or "", payload.get("filename", "")), data=msg.enviada_em, incrementar_nao_lidas=False)
    return msg, True


def update_message_ack(conta, externo_id, ack, raw_payload=None):
    if not externo_id:
        return None
    msg = (
        ZapMensagem.objects.select_related("conversa", "conversa__conta").filter(conversa__conta=conta, externo_id=externo_id).first()
    )
    if not msg:
        return None
    status = msg.status_envio
    lida = msg.lida
    if ack in (1,):
        status = ZapMensagem.StatusEnvio.ENVIADA
    elif ack in (2,):
        status = ZapMensagem.StatusEnvio.ENTREGUE
    elif ack in (3, 4):
        status = ZapMensagem.StatusEnvio.LIDA
        lida = True
    msg.status_envio = status
    msg.lida = lida
    if raw_payload:
        current = msg.raw_payload or {}
        current["ack_event"] = raw_payload
        msg.raw_payload = current
    msg.save(update_fields=["status_envio", "lida", "raw_payload", "atualizado_em"])
    return msg
