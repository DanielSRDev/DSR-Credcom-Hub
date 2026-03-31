from django.http import HttpResponseForbidden
from django.contrib.auth.views import redirect_to_login


class ModuleGroupAccessMiddleware:
    """
    Bloqueia acesso por PREFIXO de URL, baseado em grupos do Django.

    IMPORTANTE:
    - o webhook do ZapMsg precisa ficar público para o connector Node
    - então /zapmsg/webhook/ NÃO pode passar por login/grupo
    """

    RULES = {
        "/nibo/": {"NIBO"},
        "/gestao/": {"GESTAO", "GESTAO_GESTOR", "GESTAO_GESTORA", "GESTAO_USUARIO"},
        "/operacao/": {"OPERACAO", "OPERACAO_CORDENACAO", "OPERACAO_SUPERVISOR"},
        "/zapmsg/": {
            "GESTAO_GESTOR",
            "GESTAO_GESTORA",
            "GESTAO_USUARIO",
            "OPERACAO",
            "OPERACAO_CORDENACAO",
            "OPERACAO_SUPERVISOR",
        },
    }

    PUBLIC_PATHS = {
        "/zapmsg/webhook/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # libera rotas públicas antes de qualquer regra
        if path in self.PUBLIC_PATHS:
            return self.get_response(request)

        for prefix, allowed_groups in self.RULES.items():
            if path.startswith(prefix):
                user = request.user

                # não autenticado -> login
                if not user.is_authenticated:
                    return redirect_to_login(request.get_full_path())

                # superuser entra em tudo
                if user.is_superuser:
                    return self.get_response(request)

                # grupo autorizado
                if user.groups.filter(name__in=list(allowed_groups)).exists():
                    return self.get_response(request)

                return HttpResponseForbidden("Sem permissão para acessar este módulo.")

        return self.get_response(request)