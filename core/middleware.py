from django.http import HttpResponseForbidden
from django.contrib.auth.views import redirect_to_login


class ModuleGroupAccessMiddleware:
    """
    Bloqueia acesso por PREFIXO de URL, baseado em Grupos do Django.
    Ex: /nibo/ só entra quem estiver no grupo NIBO
    """

    RULES = {
        "/nibo/": {"NIBO"},
        "/gestao/": {"GESTAO", "GESTAO_GESTOR", "GESTAO_GESTORA", "GESTAO_USUARIO"},
        "/operacao/": {"OPERACAO", "OPERACAO_CORDENACAO", "OPERACAO_SUPERVISOR"},
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        for prefix, allowed_groups in self.RULES.items():
            if path.startswith(prefix):
                user = request.user

                # se não tá logado, manda pro login
                if not user.is_authenticated:
                    return redirect_to_login(request.get_full_path())

                # superuser entra em tudo (se não quiser, remove esse if)
                if user.is_superuser:
                    return self.get_response(request)

                # valida grupo
                if user.groups.filter(name__in=list(allowed_groups)).exists():
                    return self.get_response(request)

                # bloqueia
                return HttpResponseForbidden("Sem permissão para acessar este módulo.")

        # se não bateu em nenhuma regra, segue o fluxo normal
        return self.get_response(request)