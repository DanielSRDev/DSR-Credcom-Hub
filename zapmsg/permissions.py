from django.contrib.auth import get_user_model

from chat_interno.models import ChatMonitorConfig
from core import roles

User = get_user_model()


def can_monitor_all(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return ChatMonitorConfig.objects.filter(user=user, monitorado=True).exists()


def is_operacao_supervisor(user) -> bool:
    """Líder de equipe (Gestor) — faz o papel de supervisor na Operação."""
    return roles.is_gestor(user) or roles.ve_tudo(user)


def allowed_target_users(user):
    if not user.is_authenticated:
        return User.objects.none()

    base = User.objects.filter(is_active=True)

    if can_monitor_all(user):
        return base.order_by("username", "id")

    if is_operacao_supervisor(user):
        # Membros da equipe (fonte única: operacao.Equipe) + o próprio.
        operador_ids = list(roles.membros_de(user).values_list("id", flat=True))
        ids = [user.id, *operador_ids]
        return base.filter(id__in=ids).distinct().order_by("username", "id")

    return base.filter(id=user.id)


def resolve_target_user(request):
    raw = (
        request.GET.get("as_user")
        or request.POST.get("as_user")
        or request.headers.get("X-As-User")
        or ""
    ).strip()

    allowed = allowed_target_users(request.user)

    # fallback padrão: própria conta
    fallback = allowed.filter(id=request.user.id).first() or request.user

    if not raw:
        return fallback

    if not raw.isdigit():
        return fallback

    target = allowed.filter(id=int(raw)).first()
    return target or fallback


def serialize_allowed_targets(user):
    allowed = allowed_target_users(user)

    data = []
    for target in allowed:
        data.append({
            "id": target.id,
            "username": target.username,
            "label": (target.get_full_name() or target.username).strip(),
        })

    return {
        "can_monitor_all": can_monitor_all(user),
        "targets": data,
    }