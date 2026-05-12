from datetime import date
from decimal import Decimal
from io import BytesIO
import re

import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse

from .forms import AcompanhamentoGeralFiltroForm, PainelOperacaoFiltroForm
from .models import (
    CarteiraSupervisor,
    MetaOperadorCarteira,
    PainelConfiguracao,
    PainelOperacaoRegistro,
    PainelOperacaoRelatorioGeral,
    SupervisorPainel,
)
from .services import eh_status_pago, sincronizar_painel_operacao, sincronizar_relatorio_geral
from .services_acompanhamento import montar_acompanhamento_geral



GRUPOS_ACOMPANHAMENTO_GERAL = {
    "GESTAO",
    "GESTAO_GESTOR",
    "GESTAO_GESTORA",
    "GESTAO_USUARIO",
    "OPERACAO_CORDENACAO",
    "OPERACAO_SUPERVISOR",
    "SUPERVISAO",
    "SUPERVISÃO",
    "COORDENACAO",
    "COORDENAÇÃO",
    "SUPERVISOR",
}


def pode_acessar_acompanhamento_geral(user):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return user.groups.filter(name__in=GRUPOS_ACOMPANHAMENTO_GERAL).exists()


def zero_decimal(valor):
    return valor or Decimal("0.00")


def limpar_filial_exportacao(valor):
    """Remove o código operacional da filial na exportação.

    Exemplo:
    "VB29 - Residencial Drª Zélia Nunes" -> "Residencial Drª Zélia Nunes"
    """
    texto = str(valor or "").strip()

    if not texto:
        return ""

    return re.sub(r"^VB\s*\d+\s*(?:[-–—]\s*)?", "", texto, flags=re.IGNORECASE).strip()


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


def data_comparacao(item):
    return (
        item.data_pagamento if hasattr(item, "data_pagamento") and item.data_pagamento else None
    ) or item.data_emissao or item.data_acordo or item.data_etl_alteracao


def classificar_item_painel(item):
    hoje = date.today()

    if item.tem_pagamento or eh_status_pago(item.status_acordo):
        return "PAGO"

    if item.data_acordo and item.data_acordo.date() < hoje:
        return "QUEBRA"

    return "AVENCER"


def chave_contrato_item(item):
    contrato = (item.contrato or "").strip()

    if contrato:
        return contrato

    if item.aco_id:
        return f"ACO_{item.aco_id}"

    numero_acordo = (item.numero_acordo or "").strip()
    if numero_acordo:
        return f"NUM_{numero_acordo}"

    return f"REG_{item.id}"


def pegar_mais_recente_itens(itens):
    if not itens:
        return None

    return sorted(
        itens,
        key=lambda item: data_comparacao(item) or item.created_at,
        reverse=True,
    )[0]


def consolidar_itens_painel(itens):
    """
    Consolida acordos por contrato sem perder acordos pagos do mesmo mês.

    Regra operacional atual:
    - Vários PAGO no mesmo contrato/período: mantém todos.
    - Vários A VENCER no mesmo contrato/período: mantém todos.
    - Várias QUEBRA no mesmo contrato/período: mantém somente a quebra mais recente.
    - PAGO mais recente que QUEBRA antiga: mantém somente os pagos.
    - QUEBRA mais recente que o último PAGO: mantém todos os pagos + a quebra mais recente.
    - A VENCER + QUEBRA, sem pago: mantém os A VENCER e ignora a quebra.
    - PAGO + A VENCER: mantém todos os pagos + todos os A VENCER e ignora quebra antiga.
    """
    grupos = {}

    for item in itens:
        chave = chave_contrato_item(item)
        grupos.setdefault(chave, []).append(item)

    resultado = []

    for _, grupo in grupos.items():
        pagos = []
        avencers = []
        quebras = []

        for item in grupo:
            status = classificar_item_painel(item)

            if status == "PAGO":
                pagos.append(item)
            elif status == "AVENCER":
                avencers.append(item)
            else:
                quebras.append(item)

        pagos = sorted(pagos, key=lambda item: data_comparacao(item) or item.created_at, reverse=True)
        avencers = sorted(avencers, key=lambda item: data_comparacao(item) or item.created_at, reverse=True)
        quebras = sorted(quebras, key=lambda item: data_comparacao(item) or item.created_at, reverse=True)

        quebra_recente = quebras[0] if quebras else None

        # Se existe acordo A VENCER, ele representa negociação ativa/futura.
        # Nesse cenário a quebra antiga do mesmo contrato não deve entrar no painel.
        if avencers:
            resultado.extend(pagos)
            resultado.extend(avencers)
            continue

        if pagos:
            resultado.extend(pagos)

            if quebra_recente:
                ultimo_pago = pagos[0]
                data_pago = data_comparacao(ultimo_pago) or ultimo_pago.created_at
                data_quebra = data_comparacao(quebra_recente) or quebra_recente.created_at

                # Quebra só entra junto se ela for posterior ao pagamento mais recente.
                if data_quebra > data_pago:
                    resultado.append(quebra_recente)

            continue

        if quebra_recente:
            resultado.append(quebra_recente)
            continue

    return resultado

def calcular_valores_item(item):
    valor = zero_decimal(item.honorario_liquido)
    status = classificar_item_painel(item)

    emissao = valor
    pago = Decimal("0.00")
    avencer = Decimal("0.00")
    quebra = Decimal("0.00")

    if status == "PAGO":
        pago = valor
    elif status == "AVENCER":
        avencer = valor
    else:
        quebra = valor

    return {
        "status": status,
        "emissao": emissao,
        "pago": pago,
        "avencer": avencer,
        "quebra": quebra,
    }


def aplicar_filtros_painel(request):
    hoje = date.today()

    dados_iniciais = {
        "data_ini": request.GET.get("data_ini") or hoje,
        "data_fim": request.GET.get("data_fim") or hoje,
        "supervisor": request.GET.get("supervisor") or "",
        "operador": request.GET.get("operador") or "",
        "credor": request.GET.get("credor") or "",
    }

    form = PainelOperacaoFiltroForm(dados_iniciais or None)

    qs = PainelOperacaoRegistro.objects.all().order_by("-data_emissao", "-aco_id")

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

    itens_brutos = list(qs)
    itens_consolidados = consolidar_itens_painel(itens_brutos)

    return {
        "form": form,
        "qs": qs,
        "itens": itens_consolidados,
        "data_ini": data_ini,
        "data_fim": data_fim,
        "supervisor": supervisor,
        "operador": operador,
        "credor": credor,
    }


def somar_itens(itens):
    total_emissao = Decimal("0.00")
    total_pago = Decimal("0.00")
    total_avencer = Decimal("0.00")
    total_quebra = Decimal("0.00")

    for item in itens:
        valores = calcular_valores_item(item)
        total_emissao += valores["emissao"]
        total_pago += valores["pago"]
        total_avencer += valores["avencer"]
        total_quebra += valores["quebra"]

    return {
        "emissao": total_emissao,
        "pago": total_pago,
        "avencer": total_avencer,
        "quebra": total_quebra,
    }


@login_required
def painel_view(request):
    filtros = aplicar_filtros_painel(request)

    form = filtros["form"]
    itens = filtros["itens"]
    data_ini = filtros["data_ini"]
    data_fim = filtros["data_fim"]

    totais = somar_itens(itens)

    total_emissao = totais["emissao"]
    total_pago = totais["pago"]
    total_avencer = totais["avencer"]
    total_quebra = totais["quebra"]

    config = PainelConfiguracao.objects.filter(ativo=True).first()

    meta_mensal_geral = config.meta_mensal_geral if config else Decimal("0.00")
    meta_diaria_geral = config.meta_diaria_geral if config else Decimal("0.00")

    meta_diaria_restante = meta_diaria_geral - total_emissao
    if meta_diaria_restante < 0:
        meta_diaria_restante = Decimal("0.00")

    resumo_supervisores = []
    supervisores = SupervisorPainel.objects.filter(ativo=True).order_by("ordem", "nome")

    for sup in supervisores:
        itens_sup = [item for item in itens if item.supervisor_nome == sup.nome]
        totais_sup = somar_itens(itens_sup)

        resumo_supervisores.append({
            "nome": sup.nome,
            "emissao": totais_sup["emissao"],
            "pago": totais_sup["pago"],
            "avencer": totais_sup["avencer"],
            "quebra": totais_sup["quebra"],
        })

    agrupado_operadores = {}

    for item in itens:
        chave = (item.emitido_por_nome or "SEM NOME", item.supervisor_nome or "SEM SUPERVISOR")
        agrupado_operadores.setdefault(chave, {
            "emitido_por_nome": chave[0],
            "supervisor_nome": chave[1],
            "emissao": Decimal("0.00"),
            "pago": Decimal("0.00"),
            "avencer": Decimal("0.00"),
            "quebra": Decimal("0.00"),
        })

        valores = calcular_valores_item(item)
        agrupado_operadores[chave]["emissao"] += valores["emissao"]
        agrupado_operadores[chave]["pago"] += valores["pago"]
        agrupado_operadores[chave]["avencer"] += valores["avencer"]
        agrupado_operadores[chave]["quebra"] += valores["quebra"]

    ranking_base = sorted(
        agrupado_operadores.values(),
        key=lambda x: x["emissao"],
        reverse=True,
    )

    ranking_operadores = []

    for idx, item in enumerate(ranking_base, start=1):
        emissao = zero_decimal(item["emissao"])

        ranking_operadores.append({
            "posicao": idx,
            "emitido_por_nome": item["emitido_por_nome"],
            "supervisor_nome": item["supervisor_nome"],
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
        "pode_ver_acompanhamento_geral": pode_acessar_acompanhamento_geral(request.user),
    }

    return render(request, "painel_operacao/painel.html", context)


@login_required
def exportar_excel_view(request):
    filtros = aplicar_filtros_painel(request)
    itens = filtros["itens"]
    data_ini = filtros["data_ini"]
    data_fim = filtros["data_fim"]

    registros = []

    for item in itens:
        valores = calcular_valores_item(item)

        registros.append({
            "Data Referência": item.data_referencia,
            "Data Acordo": item.data_acordo,
            "Data Emissão": item.data_emissao,
            "Número Acordo": item.numero_acordo,
            "Aco ID": item.aco_id,
            "Cliente": item.cliente,
            "CPF/CNPJ": item.cpf_cnpj,
            "Contrato": item.contrato,
            "Credor ID": item.cre_id,
            "Credor": item.credor,
            "Filial": limpar_filial_exportacao(item.filial),
            "Tipo Contrato": item.tipo_contrato,
            "Tipo Negociação": item.tipo_negociacao,
            "Operador": item.emitido_por_nome,
            "Login Operador": item.emitido_por_login,
            "Supervisor": item.supervisor_nome,
            "Tem Pagamento": item.tem_pagamento,
            "Status Acordo Original": item.status_acordo,
            "Status Calculado": valores["status"],
            "Honorário Líquido": valores["emissao"],
            "Emissão": valores["emissao"],
            "Pago": valores["pago"],
            "Avencer": valores["avencer"],
            "Quebra": valores["quebra"],
        })

    df_detalhado = pd.DataFrame(registros)
    # 🔧 REMOVER TIMEZONE (CORREÇÃO DO ERRO EXCEL)
    if not df_detalhado.empty:
        for col in ["Data Referência", "Data Acordo", "Data Emissão"]:
            if col in df_detalhado.columns:
                df_detalhado[col] = pd.to_datetime(df_detalhado[col], errors="coerce")

                try:
                    df_detalhado[col] = df_detalhado[col].dt.tz_localize(None)
                except Exception:
                    pass
        totais = somar_itens(itens)

    df_resumo = pd.DataFrame([
        {
            "Período Inicial": data_ini.strftime("%d/%m/%Y") if data_ini else "",
            "Período Final": data_fim.strftime("%d/%m/%Y") if data_fim else "",
            "Total Emissão": float(totais["emissao"]),
            "Total Pago": float(totais["pago"]),
            "Total Avencer": float(totais["avencer"]),
            "Total Quebra": float(totais["quebra"]),
            "Qtd Registros": len(itens),
        }
    ])

    df_supervisores = pd.DataFrame([
        {
            "Supervisor": sup.nome,
            "Emissão": float(somar_itens([item for item in itens if item.supervisor_nome == sup.nome])["emissao"]),
            "Pago": float(somar_itens([item for item in itens if item.supervisor_nome == sup.nome])["pago"]),
            "Avencer": float(somar_itens([item for item in itens if item.supervisor_nome == sup.nome])["avencer"]),
            "Quebra": float(somar_itens([item for item in itens if item.supervisor_nome == sup.nome])["quebra"]),
        }
        for sup in SupervisorPainel.objects.filter(ativo=True).order_by("ordem", "nome")
    ])

    operadores = {}
    for item in itens:
        chave = (item.emitido_por_nome or "SEM NOME", item.supervisor_nome or "SEM SUPERVISOR")
        operadores.setdefault(chave, {
            "Operador": chave[0],
            "Supervisor": chave[1],
            "Emissão": Decimal("0.00"),
            "Pago": Decimal("0.00"),
            "Avencer": Decimal("0.00"),
            "Quebra": Decimal("0.00"),
        })

        valores = calcular_valores_item(item)
        operadores[chave]["Emissão"] += valores["emissao"]
        operadores[chave]["Pago"] += valores["pago"]
        operadores[chave]["Avencer"] += valores["avencer"]
        operadores[chave]["Quebra"] += valores["quebra"]

    df_operadores = pd.DataFrame([
        {
            "Operador": item["Operador"],
            "Supervisor": item["Supervisor"],
            "Emissão": float(item["Emissão"]),
            "Pago": float(item["Pago"]),
            "Avencer": float(item["Avencer"]),
            "Quebra": float(item["Quebra"]),
        }
        for item in sorted(operadores.values(), key=lambda x: x["Emissão"], reverse=True)
    ])

    output = BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_detalhado.to_excel(writer, sheet_name="Detalhado", index=False)
        df_resumo.to_excel(writer, sheet_name="Resumo", index=False)
        df_supervisores.to_excel(writer, sheet_name="Supervisores", index=False)
        df_operadores.to_excel(writer, sheet_name="Operadores", index=False)

        workbook = writer.book
        formato_moeda = workbook.add_format({"num_format": 'R$ #,##0.00'})
        formato_cabecalho = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
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
                    largura = max(largura, min(45, int(df[col].astype(str).map(len).max()) + 2))
                worksheet.set_column(idx, idx, largura)

            for col in ["Honorário Líquido", "Emissão", "Pago", "Avencer", "Quebra", "Total Emissão", "Total Pago", "Total Avencer", "Total Quebra"]:
                if col in df.columns:
                    idx = df.columns.get_loc(col)
                    worksheet.set_column(idx, idx, 16, formato_moeda)

            for col in ["Data Referência"]:
                if col in df.columns:
                    idx = df.columns.get_loc(col)
                    worksheet.set_column(idx, idx, 14, formato_data)

            for col in ["Data Acordo", "Data Emissão"]:
                if col in df.columns:
                    idx = df.columns.get_loc(col)
                    worksheet.set_column(idx, idx, 18, formato_datetime)

    output.seek(0)

    nome_arquivo = f"validacao_painel_operacao_{date.today().strftime('%Y%m%d')}.xlsx"

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response


@login_required
def atualizar_relatorio_geral_view(request):
    if request.method != "POST":
        return redirect("painel_operacao:painel")

    data_ini_str = request.POST.get("data_ini")
    data_fim_str = request.POST.get("data_fim")
    supervisor = request.POST.get("supervisor") or ""
    operador = request.POST.get("operador") or ""
    credor = request.POST.get("credor") or ""

    try:
        data_ini = date.fromisoformat(data_ini_str) if data_ini_str else date.today()
        data_fim = date.fromisoformat(data_fim_str) if data_fim_str else date.today()

        resultado = sincronizar_relatorio_geral(
            data_ini=data_ini,
            data_fim=data_fim,
        )

        messages.success(
            request,
            f"{resultado.get('mensagem', 'Relatório geral atualizado.')} | "
            f"Período usado: {data_ini.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')}"
        )

    except Exception as e:
        messages.error(request, f"Erro ao atualizar relatório geral: {e}")

    url = reverse("painel_operacao:painel")

    params = (
        f"?data_ini={data_ini_str or date.today().isoformat()}"
        f"&data_fim={data_fim_str or date.today().isoformat()}"
        f"&supervisor={supervisor}"
        f"&operador={operador}"
        f"&credor={credor}"
    )

    return redirect(f"{url}{params}")


@login_required
def exportar_relatorio_geral_view(request):
    data_ini_str = request.GET.get("data_ini")
    data_fim_str = request.GET.get("data_fim")
    supervisor = request.GET.get("supervisor")
    operador = request.GET.get("operador")
    credor = request.GET.get("credor")

    qs = PainelOperacaoRelatorioGeral.objects.all().order_by(
        "-data_referencia",
        "-data_pagamento",
        "-data_emissao",
    )

    if data_ini_str:
        try:
            data_ini = date.fromisoformat(data_ini_str)
            qs = qs.filter(data_referencia__gte=data_ini)
        except ValueError:
            pass

    if data_fim_str:
        try:
            data_fim = date.fromisoformat(data_fim_str)
            qs = qs.filter(data_referencia__lte=data_fim)
        except ValueError:
            pass

    if supervisor:
        qs = qs.filter(supervisor_nome=supervisor)
    if operador:
        qs = qs.filter(emitido_por_nome=operador)
    if credor:
        qs = qs.filter(credor=credor)

    registros = list(
        qs.values(
            "origem_registro",
            "data_referencia",
            "data_acordo",
            "data_emissao",
            "data_pagamento",
            "numero_acordo",
            "aco_id",
            "con_id",
            "cliente",
            "cpf_cnpj",
            "contrato",
            "cre_id",
            "credor",
            "filial",
            "tipo_contrato",
            "tipo_negociacao",
            "emitido_por_nome",
            "supervisor_nome",
            "status_acordo",
            "principal_liquido",
            "multa_liquida",
            "juros_liquido",
            "valor_parcela",
            "honorario_liquido",
            "despesa_liquida",
            "valor_total_acordo",
            "valor_pagamento_periodo",
            "valor_pago",
            "valor_avencer",
            "valor_quebra",
            "observacao_contrato",
        )
    )

    df = pd.DataFrame(registros)

    if not df.empty:
        for col in ["data_acordo", "data_emissao", "data_pagamento"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
                try:
                    df[col] = df[col].dt.tz_localize(None)
                except TypeError:
                    pass

        if "data_referencia" in df.columns:
            df["data_referencia"] = pd.to_datetime(df["data_referencia"], errors="coerce")

        if "filial" in df.columns:
            df["filial"] = df["filial"].apply(limpar_filial_exportacao)

        def calcular_status_real(row):
            if row.get("valor_pago", 0) and row.get("valor_pago", 0) > 0:
                return "PAGO"
            if row.get("valor_avencer", 0) and row.get("valor_avencer", 0) > 0:
                return "AVENCER"
            return "QUEBRA"

        df["status_real"] = df.apply(calcular_status_real, axis=1)

        valor_pagamento = pd.to_numeric(df.get("valor_pagamento_periodo", 0), errors="coerce").fillna(0)
        valor_parcela_base = pd.to_numeric(df.get("valor_parcela", 0), errors="coerce").fillna(0)
        honorario_liquido = pd.to_numeric(df.get("honorario_liquido", 0), errors="coerce").fillna(0)
        despesa_liquida = pd.to_numeric(df.get("despesa_liquida", 0), errors="coerce").fillna(0)

        # Regra nova:
        # Valor Parcela = valor do pagamento - H.O. - despesa.
        # Se a linha não tiver valor real de pagamento salvo, mantém a base antiga
        # principal + multa + juros para não gerar parcela negativa em AVENCER/QUEBRA.
        df["valor_parcela_exportacao"] = valor_parcela_base
        tem_pagamento_real = valor_pagamento > 0
        df.loc[tem_pagamento_real, "valor_parcela_exportacao"] = (
            valor_pagamento[tem_pagamento_real]
            - honorario_liquido[tem_pagamento_real]
            - despesa_liquida[tem_pagamento_real]
        )

        df["observacao_contrato"] = df.get("observacao_contrato", "")
        df["valor_recuperado_parcelamento"] = ""
        df["valor_recuperado_refinanciamento"] = ""

        df = df.rename(columns={
            "cre_id": "Cód. Contratante",
            "credor": "Contratante",
            "emitido_por_nome": "Nome Cobrador",
            "cpf_cnpj": "CPF/CNPJ",
            "cliente": "Nome do Cliente",
            "filial": "Empreendimento",
            "observacao_contrato": "Observação do Contrato",
            "con_id": "Contrato ID",
            "contrato": "Nr Contrato",
            "tipo_contrato": "Tipo do Contrato",
            "numero_acordo": "Nr Acordo",
            "tipo_negociacao": "Tipo de Negociação",
            "data_acordo": "Data Acordo",
            "status_real": "Status",
            "honorario_liquido": "Vlr. Honorário Acordo",
            "valor_total_acordo": "Vlr. Total Acordo",
            "valor_parcela_exportacao": "Valor Parcela",
            "valor_recuperado_parcelamento": "Valor Recuperado Parcelamento",
            "valor_recuperado_refinanciamento": "Valor Recuperado Refinanciamento",
            "data_pagamento": "Data Pagto Parcela",
        })

        df["Data Vecto Parcela"] = df["Data Acordo"] if "Data Acordo" in df.columns else ""

        colunas_exportacao = [
            "Cód. Contratante",
            "Contratante",
            "Nome Cobrador",
            "CPF/CNPJ",
            "Nome do Cliente",
            "Empreendimento",
            "Observação do Contrato",
            "Contrato ID",
            "Nr Contrato",
            "Tipo do Contrato",
            "Nr Acordo",
            "Tipo de Negociação",
            "Data Acordo",
            "Status",
            "Vlr. Honorário Acordo",
            "Vlr. Total Acordo",
            "Valor Parcela",
            "Valor Recuperado Parcelamento",
            "Valor Recuperado Refinanciamento",
            "Data Vecto Parcela",
            "Data Pagto Parcela",
        ]
        df = df[[col for col in colunas_exportacao if col in df.columns]]

    output = BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Relatorio Geral", index=False)

        workbook = writer.book
        worksheet = writer.sheets["Relatorio Geral"]

        formato_moeda = workbook.add_format({"num_format": 'R$ #,##0.00'})
        formato_cabecalho = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        formato_data = workbook.add_format({"num_format": "dd/mm/yyyy"})
        formato_datetime = workbook.add_format({"num_format": "dd/mm/yyyy hh:mm"})

        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, formato_cabecalho)

        for idx, col in enumerate(df.columns):
            largura = max(len(str(col)) + 2, 15)
            if not df.empty:
                largura = max(largura, min(45, int(df[col].astype(str).map(len).max()) + 2))
            worksheet.set_column(idx, idx, largura)

        for col in [
            "Vlr. Honorário Acordo",
            "Vlr. Total Acordo",
            "Valor Parcela",
        ]:
            if col in df.columns:
                idx = df.columns.get_loc(col)
                worksheet.set_column(idx, idx, 18, formato_moeda)

        for col in ["Data Acordo", "Data Vecto Parcela"]:
            if col in df.columns:
                idx = df.columns.get_loc(col)
                worksheet.set_column(idx, idx, 16, formato_data)

        for col in ["Data Pagto Parcela"]:
            if col in df.columns:
                idx = df.columns.get_loc(col)
                worksheet.set_column(idx, idx, 18, formato_datetime)

    output.seek(0)

    nome_arquivo = f"relatorio_geral_painel_operacao_{date.today().strftime('%Y%m%d')}.xlsx"

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
        data_ini = date.fromisoformat(data_ini_str) if data_ini_str else date(2026, 4, 1)
        data_fim = date.fromisoformat(data_fim_str) if data_fim_str else date.today()

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
    return redirect(f"{url}?data_ini={data_ini_str or '2026-04-01'}&data_fim={data_fim_str or date.today().isoformat()}")

def aplicar_filtros_acompanhamento(request):
    hoje = date.today()
    dados_iniciais = {
        "data_ini": request.GET.get("data_ini") or date(hoje.year, hoje.month, 1),
        "data_fim": request.GET.get("data_fim") or hoje,
        "supervisor": request.GET.get("supervisor") or "",
        "operador": request.GET.get("operador") or "",
        "credor": request.GET.get("credor") or "",
    }

    form = AcompanhamentoGeralFiltroForm(dados_iniciais or None)

    data_ini = date(hoje.year, hoje.month, 1)
    data_fim = hoje
    supervisor = None
    operador = ""
    credor = ""

    if form.is_valid():
        data_ini = form.cleaned_data.get("data_ini") or data_ini
        data_fim = form.cleaned_data.get("data_fim") or data_fim
        supervisor = form.cleaned_data.get("supervisor")
        operador = form.cleaned_data.get("operador") or ""
        credor = form.cleaned_data.get("credor") or ""

    return {
        "form": form,
        "data_ini": data_ini,
        "data_fim": data_fim,
        "supervisor": supervisor,
        "operador": operador,
        "credor": credor,
    }


@login_required
def acompanhamento_geral_view(request):
    if not pode_acessar_acompanhamento_geral(request.user):
        return HttpResponseForbidden("Você não tem permissão para acessar o Acompanhamento Geral.")

    filtros = aplicar_filtros_acompanhamento(request)

    dados = montar_acompanhamento_geral(
        data_ini=filtros["data_ini"],
        data_fim=filtros["data_fim"],
        supervisor=filtros["supervisor"],
        operador=filtros["operador"],
        credor=filtros["credor"],
    )

    context = {
        "form": filtros["form"],
        "data_ini": filtros["data_ini"],
        "data_fim": filtros["data_fim"],
        "resumo": dados["resumo"],
        "supervisores": dados["supervisores"],
        "operadores": dados["operadores"],
        "operador_carteira": dados["operador_carteira"],
    }

    return render(request, "painel_operacao/acompanhamento_geral.html", context)


@login_required
def exportar_acompanhamento_geral_view(request):
    if not pode_acessar_acompanhamento_geral(request.user):
        return HttpResponseForbidden("Você não tem permissão para exportar o Acompanhamento Geral.")

    filtros = aplicar_filtros_acompanhamento(request)

    dados = montar_acompanhamento_geral(
        data_ini=filtros["data_ini"],
        data_fim=filtros["data_fim"],
        supervisor=filtros["supervisor"],
        operador=filtros["operador"],
        credor=filtros["credor"],
    )

    resumo = dados["resumo"]

    df_resumo = pd.DataFrame([
        {
            "Data Inicial": filtros["data_ini"],
            "Data Final": filtros["data_fim"],
            "Mês Meta": resumo["mes_meta"],
            "Ano Meta": resumo["ano_meta"],
            "Meta Geral": float(resumo["meta_geral"]),
            "Faltante para Meta": float(resumo["faltante_geral"]),
            "Excedente": float(resumo["excedente_geral"]),
            "% Meta": float(resumo["pct_meta_geral"]),
            "Emissão": float(resumo["emissao"]),
            "Pago": float(resumo["pago"]),
            "A Vencer": float(resumo["avencer"]),
            "Quebra": float(resumo["quebra"]),
            "% Pago": float(resumo["pct_pago"]),
            "% A Vencer": float(resumo["pct_avencer"]),
            "% Quebra": float(resumo["pct_quebra"]),
            "Qtd Registros": resumo["qtd_registros"],
            "Qtd Metas": resumo["qtd_metas"],
        }
    ])

    df_supervisores = pd.DataFrame([
        {
            "Supervisor": item["supervisor"],
            "Meta": float(item["meta"]),
            "Emissão": float(item["emissao"]),
            "Pago": float(item["pago"]),
            "A Vencer": float(item["avencer"]),
            "Quebra": float(item["quebra"]),
            "Faltante": float(item["faltante"]),
            "Excedente": float(item["excedente"]),
            "% Meta": float(item["pct_meta"]),
            "Qtd Registros": item["qtd"],
        }
        for item in dados["supervisores"]
    ])

    df_operadores = pd.DataFrame([
        {
            "Operador": item["operador"],
            "Login": item["login"],
            "Supervisor": item["supervisor"],
            "Meta": float(item["meta"]),
            "Emissão": float(item["emissao"]),
            "Pago": float(item["pago"]),
            "A Vencer": float(item["avencer"]),
            "Quebra": float(item["quebra"]),
            "Faltante": float(item["faltante"]),
            "Excedente": float(item["excedente"]),
            "% Meta": float(item["pct_meta"]),
            "Qtd Registros": item["qtd"],
        }
        for item in dados["operadores"]
    ])

    df_operador_carteira = pd.DataFrame([
        {
            "Operador": item["operador"],
            "Login": item["login"],
            "Supervisor": item["supervisor"],
            "Credor ID": item["cre_id"],
            "Carteira": item["credor"],
            "Meta": float(item["meta"]),
            "Emissão": float(item["emissao"]),
            "Pago": float(item["pago"]),
            "A Vencer": float(item["avencer"]),
            "Quebra": float(item["quebra"]),
            "Faltante": float(item["faltante"]),
            "Excedente": float(item["excedente"]),
            "% Meta": float(item["pct_meta"]),
            "Qtd Registros": item["qtd"],
        }
        for item in dados["operador_carteira"]
    ])

    df_metas = pd.DataFrame([
        {
            "Ano": meta.ano,
            "Mês": meta.mes,
            "Supervisor": meta.carteira.supervisor.nome if meta.carteira and meta.carteira.supervisor else "",
            "Credor ID": meta.carteira.cre_id if meta.carteira else "",
            "Carteira": meta.carteira.credor_nome if meta.carteira else "",
            "Operador": meta.operador_nome,
            "Login": meta.operador_login,
            "Meta Mensal": float(meta.meta_mensal),
            "Ativo": meta.ativo,
        }
        for meta in dados["metas"]
    ])

    registros_detalhados = []
    for item in dados["queryset"]:
        status_real = "PAGO" if zero_decimal(item.valor_pago) > 0 else "AVENCER" if zero_decimal(item.valor_avencer) > 0 else "QUEBRA"
        registros_detalhados.append({
            "Origem": item.origem_registro,
            "Status Real": status_real,
            "Data Referência": item.data_referencia,
            "Data Acordo": item.data_acordo,
            "Data Emissão": item.data_emissao,
            "Data Pagamento": item.data_pagamento,
            "Número Acordo": item.numero_acordo,
            "Aco ID": item.aco_id,
            "Cliente": item.cliente,
            "CPF/CNPJ": item.cpf_cnpj,
            "Contrato": item.contrato,
            "Credor ID": item.cre_id,
            "Credor": item.credor,
            "Filial": limpar_filial_exportacao(item.filial),
            "Tipo Contrato": item.tipo_contrato,
            "Tipo Negociação": item.tipo_negociacao,
            "Operador": item.emitido_por_nome,
            "Login Operador": item.emitido_por_login,
            "Supervisor": item.supervisor_nome,
            "Status Acordo Original": item.status_acordo,
            "Principal Líquido": float(item.principal_liquido),
            "Multa Líquida": float(item.multa_liquida),
            "Juros Líquido": float(item.juros_liquido),
            "Valor Parcela": float(item.valor_parcela),
            "Honorário Líquido": float(item.honorario_liquido),
            "Vlr. Total Acordo": float(item.valor_total_acordo),
            "Emissão": float(item.valor_emissao),
            "Pago": float(item.valor_pago),
            "A Vencer": float(item.valor_avencer),
            "Quebra": float(item.valor_quebra),
        })

    df_detalhado = pd.DataFrame(registros_detalhados)

    for df in [df_resumo, df_detalhado]:
        if not df.empty:
            for col in ["Data Inicial", "Data Final", "Data Referência", "Data Acordo", "Data Emissão", "Data Pagamento"]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
                    try:
                        df[col] = df[col].dt.tz_localize(None)
                    except Exception:
                        pass

    output = BytesIO()

    abas = {
        "Resumo Geral": df_resumo,
        "Supervisores": df_supervisores,
        "Operadores": df_operadores,
        "Operador Carteira": df_operador_carteira,
        "Metas": df_metas,
        "Detalhado": df_detalhado,
    }

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for nome_aba, df in abas.items():
            df.to_excel(writer, sheet_name=nome_aba, index=False)

        workbook = writer.book
        formato_moeda = workbook.add_format({"num_format": 'R$ #,##0.00'})
        formato_percentual = workbook.add_format({"num_format": '0.00%'})
        formato_cabecalho = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        formato_data = workbook.add_format({"num_format": "dd/mm/yyyy"})
        formato_datetime = workbook.add_format({"num_format": "dd/mm/yyyy hh:mm"})

        colunas_moeda = {
            "Meta", "Meta Geral", "Meta Mensal", "Faltante", "Faltante para Meta", "Excedente",
            "Emissão", "Pago", "A Vencer", "Quebra", "Principal Líquido", "Multa Líquida",
            "Juros Líquido", "Valor Parcela", "Honorário Líquido", "Vlr. Total Acordo",
        }
        colunas_percentual = {"% Meta", "% Pago", "% A Vencer", "% Quebra"}
        colunas_data = {"Data Inicial", "Data Final", "Data Referência"}
        colunas_datetime = {"Data Acordo", "Data Emissão", "Data Pagamento"}

        for nome_aba, df in abas.items():
            worksheet = writer.sheets[nome_aba]
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, formato_cabecalho)

            for idx, col in enumerate(df.columns):
                largura = max(len(str(col)) + 2, 15)
                if not df.empty:
                    largura = max(largura, min(50, int(df[col].astype(str).map(len).max()) + 2))

                formato = None
                if col in colunas_moeda:
                    formato = formato_moeda
                elif col in colunas_data:
                    formato = formato_data
                elif col in colunas_datetime:
                    formato = formato_datetime
                elif col in colunas_percentual:
                    # As porcentagens foram salvas como 0-100 para leitura humana.
                    formato = None

                worksheet.set_column(idx, idx, largura, formato)

            worksheet.autofilter(0, 0, max(len(df), 1), max(len(df.columns) - 1, 0))
            worksheet.freeze_panes(1, 0)

    output.seek(0)

    nome_arquivo = f"acompanhamento_geral_{date.today().strftime('%Y%m%d')}.xlsx"
    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response
