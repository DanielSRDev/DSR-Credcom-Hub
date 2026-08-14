"""
Visibilidade e filtros do módulo Planilha.

Visão por cargo:
  - Gestão / superuser  -> todos os contratos.
  - Supervisor (GESTAO_GESTOR) -> contratos de todos os MEMBROS das equipes
    (operacao.Equipe) onde ele está cadastrado como Supervisor — casado pelo
    nome de cada membro (nome completo / OperadorAlias / username), igual ao
    operador comum. Não depende de carteira/cre_id.
  - Operador (OPERACAO) -> contratos onde operador_nome = nome dele
    (resolvido via nome completo / OperadorAlias / username).
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from core import roles
from operacao.models import Equipe
from painel_operacao.models import OperadorAlias

from .models import PlanilhaCompartilhamento, PlanilhaContrato


def _candidatos_nome(user) -> list[str]:
    """Nomes pelos quais o usuário pode ser reconhecido na base."""
    nomes = []
    full = (user.get_full_name() or "").strip()
    if full:
        nomes.append(full)

    uname = (getattr(user, "username", "") or "").strip()
    if uname:
        alias = OperadorAlias.objects.filter(login_original__iexact=uname, ativo=True).first()
        if alias and alias.nome_exibicao.strip():
            nomes.append(alias.nome_exibicao.strip())
        nomes.append(uname)

    # remove duplicados preservando ordem
    return list(dict.fromkeys(n for n in nomes if n))


def _q_iexact(campo: str, nomes: list[str]) -> Q:
    q = Q()
    for n in nomes:
        q |= Q(**{f"{campo}__iexact": n})
    return q


def nomes_operador_do_usuario(user) -> list[str]:
    return _candidatos_nome(user)


def nomes_da_equipe_supervisionada(user) -> list[str]:
    """Nomes (candidatos) de todos os membros das equipes onde esse usuário é Supervisor."""
    membro_ids = (
        Equipe.objects.filter(supervisores=user, ativa=True)
        .values_list("membros", flat=True)
        .distinct()
    )
    membros = get_user_model().objects.filter(id__in=list(membro_ids))
    nomes = []
    for m in membros:
        nomes.extend(_candidatos_nome(m))
    return list(dict.fromkeys(n for n in nomes if n))


def nomes_compartilhados_com_usuario(user) -> list[str]:
    """Nomes (candidatos) dos colegas cuja base foi liberada pra esse usuário
    via PlanilhaCompartilhamento (configurado no admin)."""
    colegas_ids = (
        PlanilhaCompartilhamento.objects.filter(usuario=user, ativo=True)
        .values_list("colegas", flat=True)
        .distinct()
    )
    colegas = get_user_model().objects.filter(id__in=list(colegas_ids))
    nomes = []
    for c in colegas:
        nomes.extend(_candidatos_nome(c))
    return list(dict.fromkeys(n for n in nomes if n))


def contratos_visiveis(user):
    """Queryset base de contratos que o usuário pode ver, conforme o cargo."""
    qs = PlanilhaContrato.objects.all()

    if roles.ve_tudo(user):
        return qs

    if roles.is_gestor(user):
        nomes = nomes_da_equipe_supervisionada(user)
    else:
        nomes = nomes_operador_do_usuario(user)

    # Soma bases liberadas via compartilhamento (independe do cargo).
    nomes = list(dict.fromkeys(nomes + nomes_compartilhados_com_usuario(user)))

    if not nomes:
        return qs.none()
    return qs.filter(_q_iexact("operador_nome", nomes))


# ─────────────────────────── filtros ────────────────────────────
def _to_decimal(v):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(str(v).replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def aplicar_filtros(qs, params):
    """Aplica os filtros da tela (GET) sobre o queryset visível."""
    nome = (params.get("nome") or "").strip()
    empreendimento = (params.get("empreendimento") or "").strip()
    carteira = (params.get("carteira") or "").strip()   # cre_id (seletor de base)
    operador = (params.get("operador") or "").strip()
    status_lista = [s for s in params.getlist("status") if s]

    if nome:
        qs = qs.filter(Q(nome_cliente__icontains=nome) | Q(cpf_cnpj__icontains=nome))
    if empreendimento:
        qs = qs.filter(empreendimento__icontains=empreendimento)
    if carteira:
        cre = _to_int(carteira)
        if cre is not None:
            qs = qs.filter(cre_id=cre)
    if operador:
        qs = qs.filter(operador_nome=operador)
    if status_lista:
        qs = qs.filter(status_antigo__in=status_lista)
    if params.get("so_prioridade"):
        qs = qs.filter(prioridade=True)
    if params.get("so_fila"):
        qs = qs.filter(fila_ordem__isnull=False)

    cor = (params.get("cor") or "").strip()
    if cor == "__sem__":
        qs = qs.filter(destaque_cor="")
    elif cor:
        qs = qs.filter(destaque_cor=cor)

    status_atual_lista = [s for s in params.getlist("status_atual") if s]
    if status_atual_lista:
        qs = qs.filter(status_atual__in=status_atual_lista)
    if params.get("sem_contato"):
        qs = qs.filter(status_atual_data__isnull=True)

    # "Dias sem contato" = há quantos dias foi o último evento no Virtua.
    # dias_min=N -> só quem está há N dias OU MAIS sem contato (data <= hoje-N).
    # dias_max=N -> só quem teve contato há no máximo N dias (data >= hoje-N).
    dias_min = _to_int(params.get("dias_min"))
    dias_max = _to_int(params.get("dias_max"))
    if dias_min is not None:
        qs = qs.filter(status_atual_data__lte=timezone.now() - timedelta(days=dias_min))
    if dias_max is not None:
        qs = qs.filter(status_atual_data__gte=timezone.now() - timedelta(days=dias_max))

    vmin = _to_decimal(params.get("valor_min"))
    vmax = _to_decimal(params.get("valor_max"))
    if vmin is not None:
        qs = qs.filter(vlr_total__gte=vmin)
    if vmax is not None:
        qs = qs.filter(vlr_total__lte=vmax)

    amin = _to_int(params.get("atraso_min"))
    amax = _to_int(params.get("atraso_max"))
    if amin is not None:
        qs = qs.filter(atraso_real__gte=amin)
    if amax is not None:
        qs = qs.filter(atraso_real__lte=amax)

    return qs


def opcoes_de_filtro(qs_visivel):
    """Valores distintos para popular os selects (base, operador, status)."""
    bases = list(
        qs_visivel.values("cre_id", "carteira_nome").distinct().order_by("carteira_nome")
    )
    operadores = list(
        qs_visivel.values_list("operador_nome", flat=True).distinct().order_by("operador_nome")
    )
    status = list(
        qs_visivel.exclude(status_antigo="")
        .values_list("status_antigo", flat=True).distinct().order_by("status_antigo")
    )
    status_atual = list(
        qs_visivel.exclude(status_atual="")
        .values_list("status_atual", flat=True).distinct().order_by("status_atual")
    )
    return {
        "bases": bases,
        "operadores": [o for o in operadores if o],
        "status": status,
        "status_atual": status_atual,
    }
