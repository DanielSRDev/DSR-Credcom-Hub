from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render

from .forms import PainelOperacaoFiltroForm
from .models import (
    PainelConfiguracao,
    PainelOperacaoRegistro,
    SupervisorPainel,
    CarteiraSupervisor,
)
from .services import sincronizar_painel_operacao


def zero_decimal(valor):
    return valor or Decimal("0.00")


def faixa_operador_classe(valor):
    valor = zero_decimal(valor)

    if valor < Decimal("1500"):
        return "faixa-vermelha"
    elif valor < Decimal("3000"):
        return "faixa-amarela"
    elif valor < Decimal("6000"):
        return "faixa-azul"
    elif valor < Decimal("9000"):
        return "faixa-roxa"
    return "faixa-dourada"


@login_required
def painel_view(request):
    hoje = date.today()
    data_ini_padrao = hoje
    data_fim_padrao = hoje

    dados_iniciais = {
        "data_ini": request.GET.get("data_ini") or data_ini_padrao,
        "data_fim": request.GET.get("data_fim") or data_fim_padrao,
        "supervisor": request.GET.get("supervisor") or "",
        "operador": request.GET.get("operador") or "",
        "credor": request.GET.get("credor") or "",
    }

    form = PainelOperacaoFiltroForm(dados_iniciais or None)

    qs_base = PainelOperacaoRegistro.objects.all()
    qs = qs_base.order_by("-valor_emissao", "emitido_por_nome")

    data_ini = None
    data_fim = None
    supervisor = None
    operador = None
    credor = None

    if form.is_valid():
        data_ini = form.cleaned_data.get("data_ini")
        data_fim = form.cleaned_data.get("data_fim")
        supervisor = form.cleaned_data.get("supervisor")
        operador = form.cleaned_data.get("operador")
        credor = form.cleaned_data.get("credor")

        if data_ini:
            qs = qs.filter(data_referencia__gte=data_ini)
        if data_fim:
            qs = qs.filter(data_referencia__lte=data_fim)
        if supervisor:
            qs = qs.filter(supervisor_nome=supervisor.nome)
        if operador:
            qs = qs.filter(emitido_por_nome=operador)
        if credor:
            qs = qs.filter(credor=credor)

    totais = qs.aggregate(
        total_emissao=Sum("valor_emissao"),
        total_pago=Sum("valor_pago"),
        total_avencer=Sum("valor_avencer"),
        total_quebra=Sum("valor_quebra"),
    )

    total_emissao = zero_decimal(totais["total_emissao"])
    total_pago = zero_decimal(totais["total_pago"])
    total_avencer = zero_decimal(totais["total_avencer"])
    total_quebra = zero_decimal(totais["total_quebra"])

    config = PainelConfiguracao.objects.filter(ativo=True).first()

    meta_mensal_geral = config.meta_mensal_geral if config else Decimal("0.00")
    meta_diaria_geral = config.meta_diaria_geral if config else Decimal("0.00")

    meta_diaria_restante = meta_diaria_geral - total_emissao
    if meta_diaria_restante < 0:
        meta_diaria_restante = Decimal("0.00")

    # Base só por período para cálculos globais dos supervisores
    qs_periodo = PainelOperacaoRegistro.objects.all()
    if data_ini:
        qs_periodo = qs_periodo.filter(data_referencia__gte=data_ini)
    if data_fim:
        qs_periodo = qs_periodo.filter(data_referencia__lte=data_fim)

    resumo_supervisores = []
    supervisores = SupervisorPainel.objects.filter(ativo=True).order_by("ordem", "nome")

    for sup in supervisores:
        # carteiras reais do supervisor
        cre_ids_supervisor = list(
            CarteiraSupervisor.objects.filter(
                ativo=True,
                supervisor=sup,
            ).values_list("cre_id", flat=True)
        )

        # Emissão / Pago / Avencer ainda respeitam filtros principais do painel
        qs_sup = qs.filter(supervisor_nome=sup.nome)
        agg_principal = qs_sup.aggregate(
            emissao=Sum("valor_emissao"),
            pago=Sum("valor_pago"),
            avencer=Sum("valor_avencer"),
        )

        # Quebra do card do supervisor:
        # respeita só período + carteiras do supervisor
        agg_quebra = qs_periodo.filter(
            cre_id__in=cre_ids_supervisor
        ).aggregate(
            quebra=Sum("valor_quebra")
        )

        resumo_supervisores.append({
            "nome": sup.nome,
            "emissao": zero_decimal(agg_principal["emissao"]),
            "pago": zero_decimal(agg_principal["pago"]),
            "avencer": zero_decimal(agg_principal["avencer"]),
            "quebra": zero_decimal(agg_quebra["quebra"]),
        })

    ranking_raw = (
        qs.values("emitido_por_nome", "supervisor_nome")
        .annotate(
            emissao=Sum("valor_emissao"),
            pago=Sum("valor_pago"),
            avencer=Sum("valor_avencer"),
            quebra=Sum("valor_quebra"),
        )
        .order_by("-emissao", "emitido_por_nome")
    )

    ranking_operadores = []
    for idx, item in enumerate(ranking_raw, start=1):
        emissao = zero_decimal(item["emissao"])
        ranking_operadores.append({
            "posicao": idx,
            "emitido_por_nome": item["emitido_por_nome"] or "SEM NOME",
            "supervisor_nome": item["supervisor_nome"] or "SEM SUPERVISOR",
            "emissao": emissao,
            "pago": zero_decimal(item["pago"]),
            "avencer": zero_decimal(item["avencer"]),
            "quebra": zero_decimal(item["quebra"]),
            "faixa_classe": faixa_operador_classe(emissao),
            "topo": idx == 1,
        })

    context = {
        "form": form,
        "total_emissao": total_emissao,
        "total_pago": total_pago,
        "total_avencer": total_avencer,
        "total_quebra": total_quebra,
        "meta_mensal_geral": meta_mensal_geral,
        "meta_diaria_geral": meta_diaria_geral,
        "meta_diaria_restante": meta_diaria_restante,
        "config": config,
        "resumo_supervisores": resumo_supervisores,
        "ranking_operadores": ranking_operadores,
    }
    return render(request, "painel_operacao/painel.html", context)


@login_required
def config_view(request):
    return render(request, "painel_operacao/config.html", {})


@login_required
def atualizar_view(request):
    if request.method != "POST":
        return redirect("painel_operacao:painel")

    data_ini_str = request.POST.get("data_ini")
    data_fim_str = request.POST.get("data_fim")

    try:
        data_fim = date.fromisoformat(data_fim_str) if data_fim_str else date.today()
        data_ini = date.fromisoformat(data_ini_str) if data_ini_str else (data_fim - timedelta(days=30))

        resultado = sincronizar_painel_operacao(data_ini=data_ini, data_fim=data_fim)
        messages.success(request, resultado["mensagem"])

    except Exception as e:
        messages.error(request, f"Erro ao atualizar painel: {e}")

    return redirect("painel_operacao:painel")