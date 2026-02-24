from __future__ import annotations

from functools import wraps
from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


def user_in_groups(*allowed_groups: str, allow_staff: bool = True, allow_superuser: bool = True):
    """
    Permite acesso à view apenas se o usuário estiver em um dos grupos informados.
    """
    allowed_groups = tuple(g for g in allowed_groups if g)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user

            if not user.is_authenticated:
                return redirect(settings.LOGIN_URL)

            if allow_superuser and getattr(user, "is_superuser", False):
                return view_func(request, *args, **kwargs)

            if allow_staff and getattr(user, "is_staff", False):
                return view_func(request, *args, **kwargs)

            if allowed_groups and user.groups.filter(name__in=allowed_groups).exists():
                return view_func(request, *args, **kwargs)

            return HttpResponseForbidden("Você não tem acesso a este módulo.")

        return _wrapped

    return decorator