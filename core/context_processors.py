from __future__ import annotations

from typing import Dict

GRP_COORDENACAO = {"OPERACAO_COORDENACAO"}
GRP_SUPERVISAO  = {"OPERACAO_SUPERVISOR"}
GRP_OPERACAO    = {"OPERACAO"}
GRP_GESTAO      = {"GESTAO", "GESTAO_GESTORA", "GESTAO_GESTOR", "GESTAO_USUARIO"}
GRP_NIBO        = {"NIBO"}
GRP_FINANCEIRO  = {"FINANCEIRO", "GESTAO_GESTORA"}


def _user_in_any_group(user, group_names: set[str]) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


def _modulos_bloqueados(user) -> set[str]:
    """
    Retorna o conjunto de chaves de módulo bloqueados para o usuário.
    Superuser nunca tem bloqueios aplicados.
    """
    if user.is_superuser:
        return set()
    from core.models import UsuarioRestricaoModulo
    return set(
        UsuarioRestricaoModulo.objects
        .filter(user=user)
        .values_list("modulo_bloqueado", flat=True)
    )


def nav_permissoes(request) -> Dict[str, bool]:
    """
    Disponibiliza no template flags simples para controlar a navbar.

    A flag combina duas condições:
      1. O usuário tem o grupo que dá acesso ao módulo (permissão positiva).
      2. O usuário NÃO tem restrição individual para aquele módulo (blacklist).

    Superuser vê tudo, sem exceção.
    """
    user = getattr(request, "user", None)

    falso_total = {
        "pode_ver_operacao":        False,
        "pode_ver_gestao":          False,
        "pode_ver_nibo":            False,
        "pode_ver_zapmsg":          False,
        "pode_ver_painel_operacao": False,
        "pode_ver_chat":            False,
        "pode_ver_financeiro":      False,
        "is_coordenacao":           False,
        "is_supervisao":            False,
        "is_operador":              False,
        "pode_postar_jornal":       False,
    }

    if not user or not user.is_authenticated:
        return falso_total

    if user.is_superuser:
        return {
            "pode_ver_operacao":        True,
            "pode_ver_gestao":          True,
            "pode_ver_nibo":            True,
            "pode_ver_zapmsg":          True,
            "pode_ver_painel_operacao": True,
            "pode_ver_chat":            True,
            "pode_ver_financeiro":      True,
            "is_coordenacao":           True,
            "is_supervisao":            True,
            "is_operador":              True,
            "pode_postar_jornal":       getattr(getattr(user, "perfil", None), "pode_publicar_jornal", False),
        }

    bloqueados = _modulos_bloqueados(user)

    def nao_bloqueado(modulo_key: str) -> bool:
        return modulo_key not in bloqueados

    is_coordenacao = _user_in_any_group(user, GRP_COORDENACAO)
    is_supervisao  = _user_in_any_group(user, GRP_SUPERVISAO)
    is_operador    = _user_in_any_group(user, GRP_OPERACAO)
    tem_gestao     = _user_in_any_group(user, GRP_GESTAO)
    tem_nibo       = _user_in_any_group(user, GRP_NIBO)

    # --- flags combinadas (grupo E sem restrição individual) ---
    pode_ver_operacao = (
        (is_coordenacao or is_supervisao or is_operador)
        and nao_bloqueado("operacao")
    )
    pode_ver_gestao = (
        (is_coordenacao or is_supervisao or tem_gestao)
        and nao_bloqueado("gestao")
    )
    pode_ver_nibo = (
        (is_coordenacao or tem_nibo)
        and nao_bloqueado("nibo")
    )
    pode_ver_zapmsg = (
        (is_coordenacao or is_supervisao or is_operador or tem_gestao)
        and nao_bloqueado("zapmsg")
    )
    pode_ver_painel_operacao = (
        (is_coordenacao or is_supervisao or tem_gestao or is_operador)
        and nao_bloqueado("painel_operacao")
    )
    pode_ver_chat = nao_bloqueado("chat")  # qualquer autenticado pode ver chat

    pode_ver_financeiro = (
        _user_in_any_group(user, GRP_FINANCEIRO)
        and nao_bloqueado("financeiro")
    )

    pode_postar_jornal = getattr(getattr(user, "perfil", None), "pode_publicar_jornal", False)

    return {
        "pode_ver_operacao":        pode_ver_operacao,
        "pode_ver_gestao":          pode_ver_gestao,
        "pode_ver_nibo":            pode_ver_nibo,
        "pode_ver_zapmsg":          pode_ver_zapmsg,
        "pode_ver_painel_operacao": pode_ver_painel_operacao,
        "pode_ver_chat":            pode_ver_chat,
        "pode_ver_financeiro":      pode_ver_financeiro,
        "is_coordenacao":           is_coordenacao,
        "is_supervisao":            is_supervisao,
        "is_operador":              is_operador,
        "pode_postar_jornal":       pode_postar_jornal,
    }


def jornal_ctx(request) -> Dict[str, object]:
    """
    Disponibiliza as últimas postagens do Jornal e se há novidade
    não vista pelo usuário logado (exibida uma única vez por post).
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"jornal_posts": [], "jornal_tem_novidade": False}

    from core.models import JornalPost, JornalLeitura, JornalLike

    posts = list(JornalPost.objects.all()[:20])
    ultimo = posts[0] if posts else None

    leitura, _ = JornalLeitura.objects.get_or_create(user=user)
    tem_novidade = bool(ultimo and leitura.ultimo_post_visto_id != ultimo.id)

    curtidos = set(
        JornalLike.objects.filter(user=user, post_id__in=[p.id for p in posts])
        .values_list("post_id", flat=True)
    )
    for post in posts:
        post.likes_count = post.likes.count()
        post.curtido_por_mim = post.id in curtidos
        post.pode_editar = post.autor_id == user.id or user.is_staff

    return {
        "jornal_posts": posts,
        "jornal_tem_novidade": tem_novidade,
    }


def minhas_notas(request) -> Dict[str, object]:
    """
    Disponibiliza as anotações pessoais do usuário logado para o
    modal de anotações na navbar.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"minhas_anotacoes": []}

    from core.models import AnotacaoPessoal
    return {
        "minhas_anotacoes": AnotacaoPessoal.objects.filter(user=user),
    }