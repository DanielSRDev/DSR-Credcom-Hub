import os
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Max
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core import roles

from . import services, visao
from .constants import CORES_DESTAQUE, CORES_VALIDAS
from .forms import ImportUploadForm
from .models import PlanilhaAcionamento, PlanilhaAcrescimo, PlanilhaContrato, PlanilhaStatusAcionamento


def _pode_priorizar(user) -> bool:
    return roles.ve_tudo(user) or roles.is_gestor(user)


COLUNAS_ORDENAVEIS = [
    ("nr_contrato", "Nr Contrato"),
    ("nome_cliente", "Cliente"),
    ("cpf_cnpj", "CPF/CNPJ"),
    ("empreendimento", "Empreendimento"),
    ("operador_nome", "Operador"),
    ("atraso_real", "Atraso"),
    ("vlr_total", "Vlr total"),
    ("status_antigo", "Status"),
]
CAMPOS_ORDENAVEIS = {campo for campo, _ in COLUNAS_ORDENAVEIS}


def _contrato_visivel(user, pk):
    """Devolve o contrato só se o usuário puder vê-lo (senão 404)."""
    return get_object_or_404(visao.contratos_visiveis(user), pk=pk)


def _voltar(request):
    ref = request.META.get("HTTP_REFERER")
    if ref:
        return redirect(ref)
    return redirect("planilha:index")


def _eh_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _render_card(request, contrato):
    """Renderiza o card de detalhes (partial) usado no modal da tela."""
    return render(request, "planilha/_contrato_card.html", {
        "c": contrato,
        "acrescimos": contrato.acrescimos.select_related("criado_por").all(),
        "acionamentos": contrato.acionamentos.select_related("status", "criado_por").all(),
        "status_list": PlanilhaStatusAcionamento.objects.filter(ativo=True),
        "tipos": PlanilhaAcrescimo.Tipo.choices,
        "cores": CORES_DESTAQUE,
        "pode_priorizar": _pode_priorizar(request.user),
    })


@login_required
def contrato_card(request, pk):
    """Retorna o partial do card (para abrir no modal, via AJAX)."""
    c = _contrato_visivel(request.user, pk)
    return _render_card(request, c)


@login_required
def index(request):
    """Tela de trabalho: base de contratos do usuário conforme o cargo, com filtros."""
    if not roles.tem_acesso_planilha(request.user):
        return HttpResponseForbidden("Você não tem permissão para acessar a Planilha.")

    visivel = visao.contratos_visiveis(request.user)
    opcoes = visao.opcoes_de_filtro(visivel)

    qs = visao.aplicar_filtros(visivel, request.GET).annotate(n_acrescimos=Count("acrescimos"))

    sort = request.GET.get("sort")
    sort_dir = request.GET.get("dir") if request.GET.get("dir") == "desc" else "asc"
    if sort in CAMPOS_ORDENAVEIS:
        campo = ("-" if sort_dir == "desc" else "") + sort
        qs = qs.order_by(campo, "pk")
    else:
        qs = qs.order_by(F("fila_ordem").asc(nulls_last=True), "-prioridade", "-atraso_real", "nome_cliente", "pk")

    total = qs.count()

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))

    # querystring sem 'page' para os links de paginação preservarem os filtros
    params = request.GET.copy()
    params.pop("page", None)
    querystring = params.urlencode()

    # querystring sem 'page'/'sort'/'dir' para montar os links de cabeçalho
    params_sem_sort = request.GET.copy()
    params_sem_sort.pop("page", None)
    params_sem_sort.pop("sort", None)
    params_sem_sort.pop("dir", None)
    querystring_sem_sort = params_sem_sort.urlencode()

    return render(request, "planilha/index.html", {
        "page": page,
        "total": total,
        "opcoes": opcoes,
        "filtros": request.GET,
        "filtros_status": request.GET.getlist("status"),
        "filtros_status_atual": request.GET.getlist("status_atual"),
        "querystring": querystring,
        "querystring_sem_sort": querystring_sem_sort,
        "sort_atual": sort if sort in CAMPOS_ORDENAVEIS else "",
        "dir_atual": sort_dir,
        "colunas_ordenaveis": COLUNAS_ORDENAVEIS,
        "muitas_bases": len(opcoes["bases"]) > 1,
        "cores": CORES_DESTAQUE,
        "pode_priorizar": _pode_priorizar(request.user),
    })


@login_required
def busca_global(request):
    """
    Busca por nome, CPF/CNPJ ou nº contrato em TODAS as bases, ignorando a
    visibilidade normal por operador/equipe — pra qualquer um com acesso à
    Planilha descobrir de quem é um cliente numa ligação. Mostra só o
    essencial (carteira, responsável, nº contrato), sem valor/atraso/status.
    """
    if not roles.tem_acesso_planilha(request.user):
        return HttpResponseForbidden("Você não tem permissão para acessar a Planilha.")

    q = (request.GET.get("q") or "").strip()
    resultados = []
    if q:
        from django.db.models import Q
        resultados = list(
            PlanilhaContrato.objects.filter(
                Q(nome_cliente__icontains=q) | Q(cpf_cnpj__icontains=q) | Q(nr_contrato__icontains=q)
            )
            .order_by("nome_cliente")
            .values("nr_contrato", "nome_cliente", "cpf_cnpj", "carteira_nome", "operador_nome")[:30]
        )

    return render(request, "planilha/busca_global.html", {
        "q": q,
        "resultados": resultados,
    })


@login_required
def sincronizar_status_agora(request):
    """Força agora a sincronização do Status Atual com o Virtua (sem esperar a rotina automática)."""
    if request.method != "POST":
        return redirect("planilha:index")
    if not roles.tem_acesso_planilha(request.user):
        return HttpResponseForbidden("Sem permissão.")

    if not services.adquirir_lock_sync_status():
        messages.warning(request, "Já existe uma sincronização de Status Atual em andamento. Aguarde um instante.")
        return _voltar(request)

    try:
        resultado = services.sincronizar_status_virtua()
        messages.success(
            request,
            f"Status Atual sincronizado com o Virtua: {resultado['encontrados']} contrato(s) com evento "
            f"no mês, {resultado['atualizados']} atualizado(s).",
        )
    except Exception as e:
        messages.error(request, f"Falha ao sincronizar com o Virtua: {e}")
    finally:
        services.liberar_lock_sync_status()

    return _voltar(request)


@login_required
def toggle_prioridade(request, pk):
    """Supervisor/Gestão liga/desliga a prioridade (⭐) de um contrato."""
    if request.method != "POST":
        return redirect("planilha:index")
    if not _pode_priorizar(request.user):
        return HttpResponseForbidden("Apenas supervisor/gestão pode marcar prioridade.")

    c = _contrato_visivel(request.user, pk)
    c.prioridade = not c.prioridade
    if c.prioridade:
        c.prioridade_por = request.user
        c.prioridade_em = timezone.now()
    else:
        c.prioridade_por = None
        c.prioridade_em = None
    c.save(update_fields=["prioridade", "prioridade_por", "prioridade_em"])
    if _eh_ajax(request):
        return _render_card(request, c)
    return _voltar(request)


@login_required
def definir_destaque(request, pk):
    """Operador (ou quem vê o contrato) define/limpa a cor de destaque."""
    if request.method != "POST":
        return redirect("planilha:index")

    c = _contrato_visivel(request.user, pk)
    cor = (request.POST.get("cor") or "").strip()
    if cor and cor not in CORES_VALIDAS:
        return HttpResponseForbidden("Cor inválida.")
    c.destaque_cor = cor
    c.save(update_fields=["destaque_cor"])
    if _eh_ajax(request):
        return _render_card(request, c)
    return _voltar(request)


@login_required
def exportar_selecionados(request):
    """Exporta em Excel os contratos selecionados (com telefone/e-mail/nota do operador)."""
    if request.method != "POST":
        return redirect("planilha:index")
    if not roles.tem_acesso_planilha(request.user):
        return HttpResponseForbidden("Sem permissão.")

    ids = request.POST.getlist("ids")
    qs = visao.contratos_visiveis(request.user).filter(pk__in=ids)
    if not qs.exists():
        messages.warning(request, "Selecione ao menos um contrato para exportar.")
        return redirect("planilha:index")

    conteudo = services.montar_xlsx_contratos(qs)
    resp = HttpResponse(
        conteudo,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    nome = f"planilha_selecionados_{date.today():%Y%m%d}.xlsx"
    resp["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resp


@login_required
def exportar_filtrados(request):
    """
    Exporta em Excel TODOS os contratos que batem com os filtros atuais da
    tela (mesma base/operador/status/etc. do index), não só os 50 da página
    atual nem só os marcados — para quem quer analisar a carteira inteira.
    """
    if not roles.tem_acesso_planilha(request.user):
        return HttpResponseForbidden("Sem permissão.")

    visivel = visao.contratos_visiveis(request.user)
    qs = visao.aplicar_filtros(visivel, request.GET)
    if not qs.exists():
        messages.warning(request, "Nenhum contrato encontrado com os filtros atuais.")
        return redirect("planilha:index")

    conteudo = services.montar_xlsx_contratos(qs)
    resp = HttpResponse(
        conteudo,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    nome = f"planilha_filtrados_{date.today():%Y%m%d}.xlsx"
    resp["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resp


@login_required
def prioridade_lote(request):
    """Marca vários contratos como prioridade de uma vez, ou desmarca todos."""
    if request.method != "POST":
        return redirect("planilha:index")
    if not _pode_priorizar(request.user):
        return HttpResponseForbidden("Apenas supervisor/gestão pode marcar prioridade.")

    visivel = visao.contratos_visiveis(request.user)
    acao = request.POST.get("acao")

    if acao == "marcar":
        ids = request.POST.getlist("ids")
        n = visivel.filter(pk__in=ids).update(
            prioridade=True, prioridade_por=request.user, prioridade_em=timezone.now(),
        )
        messages.success(request, f"{n} contrato(s) marcado(s) como prioridade.")
    elif acao == "desmarcar_tudo":
        n = visivel.filter(prioridade=True).update(
            prioridade=False, prioridade_por=None, prioridade_em=None,
        )
        messages.success(request, f"{n} prioridade(s) removida(s).")

    return _voltar(request)


@login_required
def destaque_lote(request):
    """Pinta (ou limpa) a cor de destaque de vários contratos de uma vez."""
    if request.method != "POST":
        return redirect("planilha:index")
    cor = (request.POST.get("cor") or "").strip()
    if cor and cor not in CORES_VALIDAS:
        return HttpResponseForbidden("Cor inválida.")
    ids = request.POST.getlist("ids")
    n = visao.contratos_visiveis(request.user).filter(pk__in=ids).update(destaque_cor=cor)
    if cor:
        messages.success(request, f"{n} contrato(s) pintado(s).")
    else:
        messages.success(request, f"Destaque removido de {n} contrato(s).")
    return _voltar(request)


@login_required
def fila_lote(request):
    """Supervisor/Gestão monta a fila ORDENADA (adiciona ao fim) ou limpa a fila."""
    if request.method != "POST":
        return redirect("planilha:index")
    if not _pode_priorizar(request.user):
        return HttpResponseForbidden("Apenas supervisor/gestão pode montar a fila.")

    visivel = visao.contratos_visiveis(request.user)
    acao = request.POST.get("acao")

    if acao == "adicionar":
        ids = request.POST.getlist("ids")  # ordem = ordem de exibição (checkboxes)
        base = visivel.aggregate(m=Max("fila_ordem"))["m"] or 0
        pos = base
        for pk in ids:
            c = visivel.filter(pk=pk, fila_ordem__isnull=True).first()
            if c:
                pos += 1
                c.fila_ordem = pos
                c.save(update_fields=["fila_ordem"])
        adicionados = pos - base
        if adicionados:
            messages.success(request, f"{adicionados} contrato(s) adicionados à fila (posições {base + 1}–{pos}).")
        else:
            messages.info(request, "Nenhum contrato novo para a fila (os selecionados já estavam nela).")
    elif acao == "limpar":
        n = visivel.filter(fila_ordem__isnull=False).update(fila_ordem=None)
        messages.success(request, f"Fila limpa ({n} contrato(s) removidos).")

    return _voltar(request)


@login_required
def contrato_detalhe(request, pk):
    """Detalhe do contrato + acréscimos (telefone/e-mail/nota)."""
    c = _contrato_visivel(request.user, pk)
    return render(request, "planilha/contrato_detalhe.html", {
        "c": c,
        "acrescimos": c.acrescimos.select_related("criado_por").all(),
        "tipos": PlanilhaAcrescimo.Tipo.choices,
        "cores": CORES_DESTAQUE,
        "pode_priorizar": _pode_priorizar(request.user),
    })


@login_required
def adicionar_acrescimo(request, pk):
    """Adiciona um telefone/e-mail/nota ao contrato."""
    if request.method != "POST":
        return redirect("planilha:contrato_detalhe", pk=pk)
    c = _contrato_visivel(request.user, pk)
    tipo = request.POST.get("tipo")
    valor = (request.POST.get("valor") or "").strip()
    if tipo in dict(PlanilhaAcrescimo.Tipo.choices) and valor:
        PlanilhaAcrescimo.objects.create(contrato=c, tipo=tipo, valor=valor, criado_por=request.user)
        if _eh_ajax(request):
            return _render_card(request, c)
        messages.success(request, "Acréscimo adicionado.")
    else:
        if _eh_ajax(request):
            return _render_card(request, c)
        messages.error(request, "Informe o tipo e o valor.")
    return redirect("planilha:contrato_detalhe", pk=pk)


@login_required
def excluir_acrescimo(request, pk):
    """Remove um acréscimo (quem criou ou gestão)."""
    if request.method != "POST":
        return redirect("planilha:index")
    ac = get_object_or_404(PlanilhaAcrescimo, pk=pk)
    if not (roles.ve_tudo(request.user) or ac.criado_por_id == request.user.id):
        return HttpResponseForbidden("Sem permissão para excluir.")
    contrato = _contrato_visivel(request.user, ac.contrato_id)  # garante visibilidade
    ac.delete()
    if _eh_ajax(request):
        return _render_card(request, contrato)
    messages.success(request, "Acréscimo removido.")
    return redirect("planilha:contrato_detalhe", pk=contrato.id)


@login_required
def registrar_acionamento(request, pk):
    """Registra um acionamento (status + comentário) no histórico do contrato."""
    if request.method != "POST":
        return redirect("planilha:contrato_detalhe", pk=pk)
    c = _contrato_visivel(request.user, pk)

    status = PlanilhaStatusAcionamento.objects.filter(
        pk=request.POST.get("status"), ativo=True,
    ).first()
    comentario = (request.POST.get("comentario") or "").strip()

    if status or comentario:
        PlanilhaAcionamento.objects.create(
            contrato=c, status=status, comentario=comentario, criado_por=request.user,
        )
        # opcionalmente tira da fila ao concluir o acionamento
        if request.POST.get("tirar_fila") == "1" and c.fila_ordem is not None:
            c.fila_ordem = None
            c.save(update_fields=["fila_ordem"])
        msg = "Acionamento registrado."
    else:
        msg = "Selecione um status ou escreva um comentário."

    if _eh_ajax(request):
        return _render_card(request, c)
    messages.info(request, msg)
    return redirect("planilha:contrato_detalhe", pk=pk)


@login_required
def sair_da_fila(request, pk):
    """Tira o contrato da fila (operador marca que já acionou)."""
    if request.method != "POST":
        return redirect("planilha:index")
    c = _contrato_visivel(request.user, pk)
    if c.fila_ordem is not None:
        c.fila_ordem = None
        c.save(update_fields=["fila_ordem"])
    if _eh_ajax(request):
        return _render_card(request, c)
    messages.success(request, "Contrato removido da fila.")
    return _voltar(request)


@login_required
def importar(request):
    """
    GET  -> formulário de upload.
    POST -> lê + valida o arquivo e mostra a pré-visualização com alerta.
            (nada é gravado nesta etapa)
    """
    if not roles.pode_importar_planilha(request.user):
        return HttpResponseForbidden("Apenas o grupo Backoffice pode importar bases.")

    if request.method != "POST":
        return render(request, "planilha/importar.html", {"form": ImportUploadForm()})

    form = ImportUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "planilha/importar.html", {"form": form})

    token = services.salvar_upload_tmp(form.cleaned_data["arquivo"])
    try:
        linhas = services.ler_planilha(services.caminho_tmp(token))
        analise = services.validar(linhas)
    except Exception as e:
        services.remover_tmp(token)
        messages.error(request, f"Não foi possível ler a planilha: {e}")
        return render(request, "planilha/importar.html", {"form": ImportUploadForm()})

    if not linhas:
        services.remover_tmp(token)
        messages.warning(request, "A planilha não tem linhas válidas na aba 'Operador'.")
        return render(request, "planilha/importar.html", {"form": ImportUploadForm()})

    return render(request, "planilha/importar.html", {
        "form": None,
        "preview": True,
        "token": token,
        "arquivo_nome": form.cleaned_data["arquivo"].name,
        "analise": analise,
    })


@login_required
def confirmar_importacao(request):
    """POST -> executa a importação (versiona + insere)."""
    if not roles.pode_importar_planilha(request.user):
        return HttpResponseForbidden("Apenas o grupo Backoffice pode importar bases.")
    if request.method != "POST":
        return redirect("planilha:importar")

    token = request.POST.get("token", "")
    arquivo_nome = request.POST.get("arquivo_nome", "")
    try:
        caminho = services.caminho_tmp(token)
        linhas = services.ler_planilha(caminho)
        analise = services.validar(linhas)
    except Exception as e:
        messages.error(request, f"Falha ao processar a importação: {e}")
        return redirect("planilha:importar")

    inconsistencias = (
        len(analise["cpf_multi_operador"])
        + len(analise["contratos_duplicados"])
        + analise["linhas_invalidas"]
    )

    if analise["tem_inconsistencia"] and request.POST.get("confirmar_erros") != "1":
        messages.error(request, "Existem inconsistências. Marque a confirmação para importar mesmo assim.")
        return render(request, "planilha/importar.html", {
            "form": None, "preview": True, "token": token,
            "arquivo_nome": arquivo_nome, "analise": analise,
        })

    modo = request.POST.get("modo_importacao") or "substituir"
    if modo not in ("substituir", "adicionar"):
        modo = "substituir"

    try:
        resultados = services.importar(
            linhas,
            user=request.user,
            importado_mesmo_com_erros=analise["tem_inconsistencia"],
            inconsistencias=inconsistencias,
            arquivo_nome=arquivo_nome,
            modo=modo,
        )
    except Exception as e:
        messages.error(request, f"Erro ao importar: {e}")
        return redirect("planilha:importar")
    finally:
        services.remover_tmp(token)

    messages.success(request, "Importação concluída.")
    return render(request, "planilha/resultado.html", {"resultados": resultados})


@login_required
def baixar_devolucao(request, nome):
    """Baixa o Excel da base antiga gerado na substituição."""
    if not roles.pode_importar_planilha(request.user):
        return HttpResponseForbidden("Sem permissão.")
    try:
        caminho = services.caminho_devolucao(nome)
    except ValueError:
        raise Http404
    if not os.path.exists(caminho):
        raise Http404("Arquivo não encontrado.")
    return FileResponse(open(caminho, "rb"), as_attachment=True, filename=nome)
