from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from .forms import PainelOperacaoFiltroForm
from .models import (
    CarteiraSupervisor,
    PainelConfiguracao,
    PainelOperacaoRegistro,
    SupervisorPainel,
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


def aplicar_filtros_painel(request):
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

    return {
        "form": form,
        "qs": qs,
        "qs_base": qs_base,
        "data_ini": data_ini,
        "data_fim": data_fim,
        "supervisor": supervisor,
        "operador": operador,
        "credor": credor,
    }


@login_required
def painel_view(request):
    filtros = aplicar_filtros_painel(request)

    form = filtros["form"]
    qs = filtros["qs"]
    data_ini = filtros["data_ini"]
    data_fim = filtros["data_fim"]

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

    qs_periodo = PainelOperacaoRegistro.objects.all()
    if data_ini:
        qs_periodo = qs_periodo.filter(data_referencia__gte=data_ini)
    if data_fim:
        qs_periodo = qs_periodo.filter(data_referencia__lte=data_fim)

    resumo_supervisores = []
    supervisores = SupervisorPainel.objects.filter(ativo=True).order_by("ordem", "nome")

    for sup in supervisores:
        cre_ids_supervisor = list(
            CarteiraSupervisor.objects.filter(
                ativo=True,
                supervisor=sup,
            ).values_list("cre_id", flat=True)
        )

        qs_sup = qs.filter(supervisor_nome=sup.nome)
        agg_principal = qs_sup.aggregate(
            emissao=Sum("valor_emissao"),
            pago=Sum("valor_pago"),
            avencer=Sum("valor_avencer"),
        )

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
def exportar_excel_view(request):
    filtros = aplicar_filtros_painel(request)
    qs = filtros["qs"]
    data_ini = filtros["data_ini"]
    data_fim = filtros["data_fim"]

    registros = list(
        qs.values(
            "data_referencia",
            "data_acordo",
            "data_emissao",
            "numero_acordo",
            "aco_id",
            "cliente",
            "cpf_cnpj",
            "contrato",
            "cre_id",
            "credor",
            "filial",
            "tipo_contrato",
            "tipo_negociacao",
            "emitido_por_nome",
            "emitido_por_login",
            "supervisor_nome",
            "tem_pagamento",
            "status_acordo",
            "honorario_liquido",
            "valor_emissao",
            "valor_pago",
            "valor_avencer",
            "valor_quebra",
        )
    )

    df_detalhado = pd.DataFrame(registros)

    if not df_detalhado.empty:
        # remove timezone das colunas datetime para o Excel aceitar
        colunas_datetime = ["data_acordo", "data_emissao"]
        for col in colunas_datetime:
            if col in df_detalhado.columns:
                df_detalhado[col] = pd.to_datetime(df_detalhado[col], errors="coerce")
                try:
                    df_detalhado[col] = df_detalhado[col].dt.tz_localize(None)
                except TypeError:
                    # se já estiver sem timezone, segue normal
                    pass

        if "data_referencia" in df_detalhado.columns:
            df_detalhado["data_referencia"] = pd.to_datetime(
                df_detalhado["data_referencia"], errors="coerce"
            )

        df_detalhado = df_detalhado.rename(columns={
            "data_referencia": "Data Referência",
            "data_acordo": "Data Acordo",
            "data_emissao": "Data Emissão",
            "numero_acordo": "Número Acordo",
            "aco_id": "Aco ID",
            "cliente": "Cliente",
            "cpf_cnpj": "CPF/CNPJ",
            "contrato": "Contrato",
            "cre_id": "Credor ID",
            "credor": "Credor",
            "filial": "Filial",
            "tipo_contrato": "Tipo Contrato",
            "tipo_negociacao": "Tipo Negociação",
            "emitido_por_nome": "Operador",
            "emitido_por_login": "Login Operador",
            "supervisor_nome": "Supervisor",
            "tem_pagamento": "Tem Pagamento",
            "status_acordo": "Status Acordo Original",
            "honorario_liquido": "Honorário Líquido",
            "valor_emissao": "Emissão",
            "valor_pago": "Pago",
            "valor_avencer": "Avencer",
            "valor_quebra": "Quebra",
        })

    totais = qs.aggregate(
        total_emissao=Sum("valor_emissao"),
        total_pago=Sum("valor_pago"),
        total_avencer=Sum("valor_avencer"),
        total_quebra=Sum("valor_quebra"),
    )

    df_resumo = pd.DataFrame([
        {
            "Período Inicial": data_ini.strftime("%d/%m/%Y") if data_ini else "",
            "Período Final": data_fim.strftime("%d/%m/%Y") if data_fim else "",
            "Total Emissão": float(zero_decimal(totais["total_emissao"])),
            "Total Pago": float(zero_decimal(totais["total_pago"])),
            "Total Avencer": float(zero_decimal(totais["total_avencer"])),
            "Total Quebra": float(zero_decimal(totais["total_quebra"])),
            "Qtd Registros": qs.count(),
        }
    ])

    df_supervisores = pd.DataFrame(
        list(
            qs.values("supervisor_nome").annotate(
                total_emissao=Sum("valor_emissao"),
                total_pago=Sum("valor_pago"),
                total_avencer=Sum("valor_avencer"),
                total_quebra=Sum("valor_quebra"),
            ).order_by("supervisor_nome")
        )
    )

    if not df_supervisores.empty:
        df_supervisores = df_supervisores.rename(columns={
            "supervisor_nome": "Supervisor",
            "total_emissao": "Emissão",
            "total_pago": "Pago",
            "total_avencer": "Avencer",
            "total_quebra": "Quebra",
        })

    df_operadores = pd.DataFrame(
        list(
            qs.values("emitido_por_nome", "supervisor_nome").annotate(
                total_emissao=Sum("valor_emissao"),
                total_pago=Sum("valor_pago"),
                total_avencer=Sum("valor_avencer"),
                total_quebra=Sum("valor_quebra"),
            ).order_by("-total_emissao", "emitido_por_nome")
        )
    )

    if not df_operadores.empty:
        df_operadores = df_operadores.rename(columns={
            "emitido_por_nome": "Operador",
            "supervisor_nome": "Supervisor",
            "total_emissao": "Emissão",
            "total_pago": "Pago",
            "total_avencer": "Avencer",
            "total_quebra": "Quebra",
        })

    output = BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_detalhado.to_excel(writer, sheet_name="Detalhado", index=False)
        df_resumo.to_excel(writer, sheet_name="Resumo", index=False)
        df_supervisores.to_excel(writer, sheet_name="Supervisores", index=False)
        df_operadores.to_excel(writer, sheet_name="Operadores", index=False)

        workbook = writer.book

        formato_moeda = workbook.add_format({"num_format": 'R$ #,##0.00'})
        formato_cabecalho = workbook.add_format({
            "bold": True,
            "bg_color": "#D9EAF7",
            "border": 1,
        })
        formato_data = workbook.add_format({"num_format": "dd/mm/yyyy"})
        formato_datetime = workbook.add_format({"num_format": "dd/mm/yyyy hh:mm"})

        for nome_aba, df in {
            "Detalhado": df_detalhado,
            "Resumo": df_resumo,
            "Supervisores": df_supervisores,
            "Operadores": df_operadores,
        }.items():
            worksheet = writer.sheets[nome_aba]

            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, formato_cabecalho)

            for idx, col in enumerate(df.columns):
                largura = max(len(str(col)) + 2, 15)
                if not df.empty:
                    largura = max(largura, min(40, int(df[col].astype(str).map(len).max()) + 2))
                worksheet.set_column(idx, idx, largura)

            if nome_aba == "Detalhado":
                colunas_moeda = [
                    "Honorário Líquido", "Emissão", "Pago", "Avencer", "Quebra"
                ]
                colunas_data = ["Data Referência"]
                colunas_datetime = ["Data Acordo", "Data Emissão"]

                for col in colunas_moeda:
                    if col in df.columns:
                        idx = df.columns.get_loc(col)
                        worksheet.set_column(idx, idx, 16, formato_moeda)

                for col in colunas_data:
                    if col in df.columns:
                        idx = df.columns.get_loc(col)
                        worksheet.set_column(idx, idx, 14, formato_data)

                for col in colunas_datetime:
                    if col in df.columns:
                        idx = df.columns.get_loc(col)
                        worksheet.set_column(idx, idx, 18, formato_datetime)

            if nome_aba in ["Resumo", "Supervisores", "Operadores"]:
                for col in df.columns:
                    if col in ["Emissão", "Pago", "Avencer", "Quebra", "Total Emissão", "Total Pago", "Total Avencer", "Total Quebra"]:
                        idx = df.columns.get_loc(col)
                        worksheet.set_column(idx, idx, 16, formato_moeda)

    output.seek(0)

    nome_arquivo = f"validacao_painel_operacao_{date.today().strftime('%Y%m%d')}.xlsx"

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response


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
        try:
            data_ini = date.fromisoformat(data_ini_str) if data_ini_str else date(2026, 4, 1)
        except ValueError:
            data_ini = datetime.strptime(data_ini_str, "%d/%m/%Y").date() if data_ini_str else date(2026, 4, 1)

        try:
            data_fim = date.fromisoformat(data_fim_str) if data_fim_str else date.today()
        except ValueError:
            data_fim = datetime.strptime(data_fim_str, "%d/%m/%Y").date() if data_fim_str else date.today()

        resultado = sincronizar_painel_operacao(
            data_ini=data_ini,
            data_fim=data_fim,
        )

        messages.success(
            request,
            f"{resultado['mensagem']} | Período usado: {data_ini.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')}"
        )

    except Exception as e:
        messages.error(request, f"Erro ao atualizar painel: {e}")

    url = reverse("painel_operacao:painel")
    return redirect(f"{url}?data_ini={data_ini.isoformat()}&data_fim={data_fim.isoformat()}")