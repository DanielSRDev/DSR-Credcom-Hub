"""
Camada central de papéis (cargos) e equipes do sistema.

Fonte ÚNICA de verdade para "que cargo o usuário tem" e "quem é da equipe de
quem". Middleware, views de Gestão/Operação, chat, zapmsg e painel devem
importar daqui em vez de checar grupo na mão (ver core/grupos.py para os nomes).

Equipe = operacao.Equipe (cadastro único). O chat e o zapmsg, que antes usavam
chat_interno.ChatVinculoOperador, passam a ler a equipe daqui também.
"""
from __future__ import annotations

from django.contrib.auth.models import User

from . import grupos


# ── checagem de cargo ────────────────────────────────────────────────────────
def _tem_grupo(user, *nomes) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.groups.filter(name__in=nomes).exists()


def is_gestao(user) -> bool:
    """Diretoria — vê tudo."""
    return _tem_grupo(user, grupos.GESTAO)


def is_gestor(user) -> bool:
    """Gestor / líder de equipe (faz o papel de supervisor na Operação)."""
    return _tem_grupo(user, grupos.GESTAO_GESTOR)


def is_pos_acordo(user) -> bool:
    return _tem_grupo(user, grupos.POS_ACORDO)


def is_operacao(user) -> bool:
    return _tem_grupo(user, grupos.OPERACAO)


def is_financeiro(user) -> bool:
    return _tem_grupo(user, grupos.FINANCEIRO)


def is_juridico(user) -> bool:
    return _tem_grupo(user, grupos.JURIDICO)


def ve_tudo(user) -> bool:
    """Acesso total: superuser ou Diretoria (GESTAO)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return bool(user.is_superuser) or is_gestao(user)


# ── grupos de cargos por módulo (cargo dá direito de acesso) ─────────────────
CARGOS_OPERACAO = (
    grupos.GESTAO, grupos.GESTAO_GESTOR, grupos.POS_ACORDO,
    grupos.OPERACAO, grupos.JURIDICO,
)
CARGOS_GESTAO = (grupos.GESTAO, grupos.GESTAO_GESTOR)
CARGOS_NIBO   = (grupos.GESTAO, grupos.FINANCEIRO)
CARGOS_PAINEL = (grupos.GESTAO, grupos.GESTAO_GESTOR, grupos.OPERACAO)


def tem_acesso_operacao(user) -> bool:
    return ve_tudo(user) or _tem_grupo(user, *CARGOS_OPERACAO)


def tem_acesso_gestao(user) -> bool:
    return ve_tudo(user) or _tem_grupo(user, *CARGOS_GESTAO)


def tem_acesso_nibo(user) -> bool:
    return ve_tudo(user) or _tem_grupo(user, *CARGOS_NIBO)


def tem_acesso_zapmsg(user) -> bool:
    return ve_tudo(user) or _tem_grupo(user, grupos.GESTAO_GESTOR, grupos.OPERACAO)


def tem_acesso_painel(user) -> bool:
    return ve_tudo(user) or _tem_grupo(user, *CARGOS_PAINEL)


def tem_acesso_financeiro(user) -> bool:
    return ve_tudo(user) or _tem_grupo(user, grupos.FINANCEIRO)


# ── equipes (fonte única: operacao.Equipe) ──────────────────────────────────
def supervisores_de(user):
    """Supervisores diretos = supervisores das equipes ATIVAS onde o usuário é membro."""
    if not user or not getattr(user, "is_authenticated", False):
        return User.objects.none()
    equipes = user.operacao_equipes.filter(ativa=True)
    return (
        User.objects.filter(operacao_equipes_supervisionadas__in=equipes, is_active=True)
        .exclude(id=user.id)
        .distinct()
    )


def membros_de(user):
    """Membros das equipes ATIVAS que o usuário supervisiona (sem incluir ele mesmo)."""
    if not user or not getattr(user, "is_authenticated", False):
        return User.objects.none()
    equipes = user.operacao_equipes_supervisionadas.filter(ativa=True)
    return (
        User.objects.filter(operacao_equipes__in=equipes, is_active=True)
        .exclude(id=user.id)
        .distinct()
    )


def colegas_de_equipe(user):
    """Outros membros das equipes ATIVAS a que o usuário pertence (usado p/ o chat do Jurídico)."""
    if not user or not getattr(user, "is_authenticated", False):
        return User.objects.none()
    equipes = user.operacao_equipes.filter(ativa=True)
    return (
        User.objects.filter(operacao_equipes__in=equipes, is_active=True)
        .exclude(id=user.id)
        .distinct()
    )


def usuarios_no_cargo(*cargos):
    """Usuários ativos que pertencem a qualquer um dos cargos informados."""
    return User.objects.filter(is_active=True, groups__name__in=cargos).distinct()
