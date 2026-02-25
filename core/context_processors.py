from __future__ import annotations

from typing import Dict

# Ajuste os nomes EXATOS dos seus grupos aqui
GRP_COORDENACAO = {"OPERACAO_COORDENACAO"}  # coordenação (manda em tudo)
GRP_SUPERVISAO = {"OPERACAO_SUPERVISOR"}    # supervisão (gestao + operacao)
GRP_OPERACAO = {"OPERACAO"}                # operador (operacao)
GRP_GESTAO = {"GESTAO", "GESTAO_GESTORA", "GESTAO_GESTOR", "GESTAO_USUARIO"}  # se existir
GRP_NIBO = {"NIBO"}                        # nibo


def _user_in_any_group(user, group_names: set[str]) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


def nav_permissoes(request) -> Dict[str, bool]:
    """
    Disponibiliza no template flags simples para controlar a navbar.
    Coordenação: vê tudo.
    Supervisão: vê Gestão e Operação.
    Operador: vê somente Operação.
    """
    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return {
            "pode_ver_operacao": False,
            "pode_ver_gestao": False,
            "pode_ver_nibo": False,
            "is_coordenacao": False,
            "is_supervisao": False,
            "is_operador": False,
        }

    # Superuser vê tudo
    if user.is_superuser:
        return {
            "pode_ver_operacao": True,
            "pode_ver_gestao": True,
            "pode_ver_nibo": True,
            "is_coordenacao": True,
            "is_supervisao": True,
            "is_operador": True,
        }

    is_coordenacao = _user_in_any_group(user, GRP_COORDENACAO)
    is_supervisao = _user_in_any_group(user, GRP_SUPERVISAO)
    is_operador = _user_in_any_group(user, GRP_OPERACAO)

    # Regra de negócio (do jeito que você descreveu)
    pode_ver_operacao = is_coordenacao or is_supervisao or is_operador
    pode_ver_gestao = is_coordenacao or is_supervisao or _user_in_any_group(user, GRP_GESTAO)
    pode_ver_nibo = is_coordenacao or _user_in_any_group(user, GRP_NIBO)

    return {
        "pode_ver_operacao": pode_ver_operacao,
        "pode_ver_gestao": pode_ver_gestao,
        "pode_ver_nibo": pode_ver_nibo,
        "is_coordenacao": is_coordenacao,
        "is_supervisao": is_supervisao,
        "is_operador": is_operador,
    }