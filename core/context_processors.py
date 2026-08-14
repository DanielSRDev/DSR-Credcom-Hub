from __future__ import annotations

from typing import Dict

from django.conf import settings

from core import roles


def versao_site(request) -> Dict[str, str]:
    """Disponibiliza a versão do site (Credcom Hub) para a navbar."""
    return {"site_version": getattr(settings, "SITE_VERSION", "")}


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


def _modulos_liberados(user) -> set[str]:
    """
    Retorna o conjunto de chaves de módulo liberados individualmente
    (whitelist) para o usuário. Superuser não precisa — já vê tudo.
    """
    if user.is_superuser:
        return set()
    from core.models import UsuarioLiberacaoModulo
    return set(
        UsuarioLiberacaoModulo.objects
        .filter(user=user)
        .values_list("modulo_liberado", flat=True)
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
        "pode_ver_planilha":        False,
        "pode_importar_planilha":   False,
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
            "pode_ver_planilha":        True,
            "pode_importar_planilha":   True,
            "is_coordenacao":           True,
            "is_supervisao":            True,
            "is_operador":              True,
            "pode_postar_jornal":       getattr(getattr(user, "perfil", None), "pode_publicar_jornal", False),
        }

    bloqueados = _modulos_bloqueados(user)
    liberados  = _modulos_liberados(user)

    def nao_bloqueado(modulo_key: str) -> bool:
        return modulo_key not in bloqueados

    def liberado(modulo_key: str) -> bool:
        return modulo_key in liberados

    ve_tudo       = roles.ve_tudo(user)
    is_coordenacao = ve_tudo                       # compat: Diretoria = acesso total
    is_supervisao  = roles.is_gestor(user)         # compat: gestor/líder
    is_operador    = roles.is_operacao(user)       # compat: operador comum

    tem_operacao   = roles.tem_acesso_operacao(user)
    tem_gestao     = roles.tem_acesso_gestao(user)
    tem_nibo       = roles.tem_acesso_nibo(user)
    tem_zapmsg     = roles.tem_acesso_zapmsg(user)
    tem_painel     = roles.tem_acesso_painel(user)
    tem_financeiro = roles.tem_acesso_financeiro(user)
    tem_planilha   = roles.tem_acesso_planilha(user)

    # --- flags combinadas ((cargo OU liberação individual) E sem bloqueio) ---
    pode_ver_operacao = (tem_operacao or liberado("operacao")) and nao_bloqueado("operacao")
    pode_ver_gestao   = (tem_gestao   or liberado("gestao"))   and nao_bloqueado("gestao")
    pode_ver_nibo     = (tem_nibo     or liberado("nibo"))     and nao_bloqueado("nibo")
    pode_ver_zapmsg   = (tem_zapmsg   or liberado("zapmsg"))   and nao_bloqueado("zapmsg")
    pode_ver_painel_operacao = (tem_painel or liberado("painel_operacao")) and nao_bloqueado("painel_operacao")
    pode_ver_chat = nao_bloqueado("chat")  # qualquer autenticado pode ver chat
    pode_ver_financeiro = (tem_financeiro or liberado("financeiro")) and nao_bloqueado("financeiro")
    pode_ver_planilha = (tem_planilha or liberado("planilha")) and nao_bloqueado("planilha")
    pode_importar_planilha = pode_ver_planilha and roles.pode_importar_planilha(user)

    pode_postar_jornal = getattr(getattr(user, "perfil", None), "pode_publicar_jornal", False)

    return {
        "pode_ver_operacao":        pode_ver_operacao,
        "pode_ver_gestao":          pode_ver_gestao,
        "pode_ver_nibo":            pode_ver_nibo,
        "pode_ver_zapmsg":          pode_ver_zapmsg,
        "pode_ver_painel_operacao": pode_ver_painel_operacao,
        "pode_ver_chat":            pode_ver_chat,
        "pode_ver_financeiro":      pode_ver_financeiro,
        "pode_ver_planilha":        pode_ver_planilha,
        "pode_importar_planilha":   pode_importar_planilha,
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

    from collections import defaultdict

    from core.models import JornalPost, JornalLeitura, JornalReacao
    from core.views import _resumo_reacoes

    posts = list(
        JornalPost.objects.prefetch_related("comentarios__user").all()[:20]
    )
    ultimo = posts[0] if posts else None

    leitura, _ = JornalLeitura.objects.get_or_create(user=user)
    tem_novidade = bool(ultimo and leitura.ultimo_post_visto_id != ultimo.id)

    # Coleta todos os comentários visíveis e todas as reações (posts +
    # comentários) em poucas queries, depois agrupa em memória.
    post_ids = [p.id for p in posts]
    comentarios_por_post = {p.id: list(p.comentarios.all()) for p in posts}
    coment_ids = [c.id for cs in comentarios_por_post.values() for c in cs]

    reacoes_post = defaultdict(list)
    for r in JornalReacao.objects.filter(post_id__in=post_ids).select_related("user"):
        reacoes_post[r.post_id].append(r)

    reacoes_coment = defaultdict(list)
    if coment_ids:
        for r in JornalReacao.objects.filter(
            comentario_id__in=coment_ids
        ).select_related("user"):
            reacoes_coment[r.comentario_id].append(r)

    for post in posts:
        post.pode_editar = post.autor_id == user.id or user.is_staff
        post.reacoes_resumo = _resumo_reacoes(reacoes_post.get(post.id, []), user)
        post.lista_comentarios = comentarios_por_post[post.id]
        for c in post.lista_comentarios:
            c.pode_excluir = c.user_id == user.id or user.is_staff
            c.reacoes_resumo = _resumo_reacoes(reacoes_coment.get(c.id, []), user)

    return {
        "jornal_posts": posts,
        "jornal_tem_novidade": tem_novidade,
        "jornal_emojis": JornalReacao.EMOJIS,
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