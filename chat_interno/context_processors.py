from .services import unread_count


def chat_nav(request):
    """
    Disponibiliza:
      - chat_unread_total
    Sem quebrar login/qualquer template.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"chat_unread_total": 0}

    try:
        total = unread_count(user)
    except Exception:
        total = 0

    return {"chat_unread_total": total}