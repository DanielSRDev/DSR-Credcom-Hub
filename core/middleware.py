from django.http import HttpResponseForbidden
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect

from core import grupos

PRIMEIRO_ACESSO_URL = "/accounts/primeiro-acesso/"

# Rotas liberadas mesmo quando deve_trocar_senha = True
_LIBERADAS_PRIMEIRO_ACESSO = {
    PRIMEIRO_ACESSO_URL,
    "/accounts/logout/",
    "/accounts/login/",
    "/admin/",
}


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

    # Cargos por módulo (modelo dos 6 cargos). Liberação individual (whitelist)
    # complementa estas regras; bloqueio individual sempre vence.
    # A regra mais específica (/operacao/painel/) tem precedência sobre /operacao/.
    RULES = {
        "/nibo/":            {grupos.GESTAO, grupos.FINANCEIRO},
        "/gestao/":          {grupos.GESTAO, grupos.GESTAO_GESTOR},
        "/operacao/painel/": {grupos.GESTAO, grupos.GESTAO_GESTOR, grupos.OPERACAO},
        "/operacao/":        {grupos.GESTAO, grupos.GESTAO_GESTOR, grupos.POS_ACORDO,
                              grupos.OPERACAO, grupos.JURIDICO},
        "/zapmsg/":          {grupos.GESTAO, grupos.GESTAO_GESTOR, grupos.OPERACAO},
        "/chat/":            set(),  # acesso livre para autenticados — sem grupo exigido
        "/financeiro/":      {grupos.GESTAO, grupos.FINANCEIRO},
        # "Backoffice" (grupo, não cargo) entra p/ importar a base.
        "/planilha/":        {grupos.GESTAO, grupos.GESTAO_GESTOR, grupos.OPERACAO, "Backoffice"},
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
        "/financeiro/":      "financeiro",
        "/planilha/":        "planilha",
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

    def _modulo_liberado_para(self, user, modulo_key: str) -> bool:
        """
        Retorna True se o usuário tem liberação individual (whitelist) para o
        módulo — concede acesso mesmo sem o grupo. Bloqueio vence liberação.
        """
        if not modulo_key:
            return False
        from core.models import UsuarioLiberacaoModulo
        return UsuarioLiberacaoModulo.objects.filter(
            user=user,
            modulo_liberado=modulo_key,
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

        # --- primeiro acesso: força troca de senha ---
        user = request.user
        if (
            user.is_authenticated
            and not any(path.startswith(p) for p in _LIBERADAS_PRIMEIRO_ACESSO)
        ):
            try:
                if user.perfil.deve_trocar_senha:
                    return redirect(PRIMEIRO_ACESSO_URL)
            except Exception:
                pass  # perfil ainda não criado → deixa passar normalmente

        # Avalia o prefixo MAIS específico primeiro (/operacao/painel/ antes de /operacao/).
        for prefix in sorted(self.RULES, key=len, reverse=True):
            if not path.startswith(prefix):
                continue
            allowed_groups = self.RULES[prefix]

            user = request.user

            # não autenticado → login
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            # superuser passa por tudo — sem restrição individual
            if user.is_superuser:
                return self.get_response(request)

            modulo_key = self._get_modulo_key(path)

            # --- camada 1: grupo OU liberação individual (whitelist) ---
            em_grupo = (
                not allowed_groups
                or user.groups.filter(name__in=list(allowed_groups)).exists()
            )
            liberado = self._modulo_liberado_para(user, modulo_key)
            if not em_grupo and not liberado:
                return HttpResponseForbidden("Sem permissão para acessar este módulo.")

            # --- camada 2: restrição individual por usuário (bloqueio vence) ---
            if modulo_key and self._modulo_bloqueado_para(user, modulo_key):
                return HttpResponseForbidden(
                    "Seu acesso a este módulo foi restrito pelo administrador."
                )

            return self.get_response(request)

        return self.get_response(request)