from django.http import HttpResponseForbidden
from django.contrib.auth.views import redirect_to_login


class ModuleGroupAccessMiddleware:
    """
    Bloqueia acesso por PREFIXO de URL, baseado em grupos do Django.

    Camada 1 — grupo: verifica se o usuário pertence a algum grupo
    autorizado para o prefixo da URL.

    Camada 2 — restrição individual: mesmo que o grupo autorize,
    um registro em UsuarioRestricaoModulo pode bloquear o acesso
    para um usuário específico. Superuser nunca é bloqueado.

    IMPORTANTE:
    - o webhook do ZapMsg precisa ficar público para o connector Node
    - então /zapmsg/webhook/ NÃO pode passar por login/grupo
    """

    RULES = {
        "/nibo/":     {"NIBO"},
        "/gestao/":   {"GESTAO", "GESTAO_GESTOR", "GESTAO_GESTORA", "GESTAO_USUARIO"},
        "/operacao/": {"OPERACAO", "OPERACAO_CORDENACAO", "OPERACAO_SUPERVISOR"},
        "/zapmsg/": {
            "GESTAO_GESTOR",
            "GESTAO_GESTORA",
            "GESTAO_USUARIO",
            "OPERACAO",
            "OPERACAO_CORDENACAO",
            "OPERACAO_SUPERVISOR",
        },
        "/chat/": set(),  # acesso livre para autenticados — sem grupo exigido
    }

    # Mapeamento prefixo → chave do Modulo em UsuarioRestricaoModulo
    # Prefixos mais específicos devem vir primeiro na resolução.
    PREFIX_TO_MODULO = {
        "/operacao/painel/": "painel_operacao",
        "/nibo/":            "nibo",
        "/gestao/":          "gestao",
        "/operacao/":        "operacao",
        "/zapmsg/":          "zapmsg",
        "/chat/":            "chat",
    }

    PUBLIC_PATHS = {
        "/zapmsg/webhook/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _modulo_bloqueado_para(self, user, modulo_key: str) -> bool:
        """
        Retorna True se o usuário tem restrição ativa para o módulo.
        Importação local para evitar problema de import circular na
        inicialização do Django (models ainda não carregados no __init__).
        """
        from core.models import UsuarioRestricaoModulo
        return UsuarioRestricaoModulo.objects.filter(
            user=user,
            modulo_bloqueado=modulo_key,
        ).exists()

    def _get_modulo_key(self, path: str) -> str | None:
        """
        Retorna a chave de módulo mais específica que corresponde ao path.
        /operacao/painel/ tem precedência sobre /operacao/.
        """
        for prefix in sorted(self.PREFIX_TO_MODULO, key=len, reverse=True):
            if path.startswith(prefix):
                return self.PREFIX_TO_MODULO[prefix]
        return None

    # ------------------------------------------------------------------
    # __call__
    # ------------------------------------------------------------------

    def __call__(self, request):
        path = request.path

        # rotas públicas — sem nenhuma verificação
        if path in self.PUBLIC_PATHS:
            return self.get_response(request)

        for prefix, allowed_groups in self.RULES.items():
            if not path.startswith(prefix):
                continue

            user = request.user

            # não autenticado → login
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            # superuser passa por tudo — sem restrição individual
            if user.is_superuser:
                return self.get_response(request)

            # --- camada 1: grupo ---
            if allowed_groups and not user.groups.filter(name__in=list(allowed_groups)).exists():
                return HttpResponseForbidden("Sem permissão para acessar este módulo.")

            # --- camada 2: restrição individual por usuário ---
            modulo_key = self._get_modulo_key(path)
            if modulo_key and self._modulo_bloqueado_para(user, modulo_key):
                return HttpResponseForbidden(
                    "Seu acesso a este módulo foi restrito pelo administrador."
                )

            return self.get_response(request)

        return self.get_response(request)