# Gestao/views.py
from __future__ import annotations

import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from core.models import ConfiguracaoSeguranca, UsuarioLiberacaoModulo
from core.services import finalizar_executados_vencidos
from core import roles
from core.grupos import GESTAO, GESTAO_GESTOR
from .forms import TarefaForm, ComentarioForm, AnexoForm, DevolucaoForm
from .models import Tarefa, Comentario, Anexo

User = get_user_model()

# ============================================================
# RBAC
# ============================================================
# Modelo dos 6 cargos:
#   - GESTAO (Diretoria) / superuser  -> vê e edita TUDO.
#   - GESTAO_GESTOR                   -> participa do módulo (vê os cards ligados
#                                        a ele e cria para outros), NÃO edita o
#                                        quadro inteiro.
#   - Liberação individual (ex.: Jurídico) -> acessa o módulo como participante.

GESTAO_CARGOS = [GESTAO, GESTAO_GESTOR]


def in_group(user, group_name: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=group_name).exists()


def tem_acesso_gestao(user) -> bool:
    if not user.is_authenticated:
        return False
    if roles.tem_acesso_gestao(user):
        return True
    # liberação individual de módulo (whitelist) — ex.: pessoa do Jurídico
    return UsuarioLiberacaoModulo.objects.filter(user=user, modulo_liberado="gestao").exists()


def pode_editar(user) -> bool:
    # Edição/visão total do quadro: apenas Diretoria (GESTAO) ou superuser.
    return roles.ve_tudo(user)


def pode_criar(user) -> bool:
    return tem_acesso_gestao(user)


def pode_prioridade(user) -> bool:
    return pode_editar(user)


def pode_deletar(user) -> bool:
    return roles.ve_tudo(user)


def pode_ver_tarefa(user, tarefa: Tarefa) -> bool:
    if not user.is_authenticated:
        return False
    if pode_editar(user):
        return True
    return (
        tarefa.atribuida_para_id == user.id
        or tarefa.criada_por_id == user.id
        or tarefa.executor_id == user.id
    )


def pode_executar(user, tarefa: Tarefa) -> bool:
    if not user.is_authenticated:
        return False
    return pode_editar(user) or tarefa.atribuida_para_id == user.id


def pode_marcar_executado(user, tarefa: Tarefa) -> bool:
    if not user.is_authenticated:
        return False
    return pode_editar(user) or tarefa.executor_id == user.id


def pode_finalizar(user, tarefa: Tarefa) -> bool:
    if not user.is_authenticated:
        return False
    return pode_editar(user) or tarefa.criada_por_id == user.id


def pode_validar(user, tarefa: Tarefa) -> bool:
    """
    Validar (mover EXECUTADO → PENDENTE ou FEITA):
    somente o criador do card ou gestor/gestora.
    """
    if not user.is_authenticated:
        return False
    return pode_editar(user) or tarefa.criada_por_id == user.id


# ============================================================
# HELPERS
# ============================================================

def _next_or(request, default_url: str):
    return request.POST.get("next") or request.GET.get("next") or default_url


def _annotate_counts(qs):
    return qs.annotate(
        anexos_count=Count("anexos", distinct=True),
        comentarios_count=Count("comentarios", distinct=True),
    )


def _build_base_filtrado(request):
    """
    Aplica filtros de data, responsável e busca (título ou código).

    Mesma regra do `quadro` para manter KPIs e contadores consistentes:
      - Usuário sem permissão de gestor fica travado em si mesmo.
      - Com f_user: tudo que tem QUALQUER relação com esse usuário
        (atribuído, executor ou criador).
      - Sem f_user: tudo que tem relação com o LOGADO.
    """
    f_data_ini = request.GET.get("data_ini") or ""
    f_data_fim = request.GET.get("data_fim") or ""
    f_user     = request.GET.get("user") or ""
    f_busca    = (request.GET.get("busca") or "").strip()

    base = Tarefa.objects.select_related("criada_por", "atribuida_para", "executor")

    if not pode_editar(request.user):
        f_user = str(request.user.id)

    if f_data_ini:
        base = base.filter(prazo__date__gte=f_data_ini)
    if f_data_fim:
        base = base.filter(prazo__date__lte=f_data_fim)

    if f_busca:
        base = base.filter(
            Q(codigo__iexact=f_busca) | Q(titulo__icontains=f_busca)
        )

    if f_user:
        try:
            uid = int(f_user)
            base = base.filter(
                Q(atribuida_para_id=uid)
                | Q(executor_id=uid)
                | Q(criada_por_id=uid)
            ).distinct()
        except (ValueError, TypeError):
            pass
    else:
        base = base.filter(
            Q(atribuida_para=request.user)
            | Q(executor=request.user)
            | Q(criada_por=request.user)
        ).distinct()

    return base


# ============================================================
# QUADRO
# ============================================================

def _voltar_url(request):
    """URL do quadro (com filtros atuais) usada nos 'next' dos cards.
    Reconstruída a partir de request.GET para ser igual tanto na página
    cheia quanto no endpoint /partial/cards/ do auto-refresh."""
    base = reverse("gestao:quadro")
    qs = request.GET.urlencode()
    return f"{base}?{qs}" if qs else base


def _contexto_quadro(request):
    # Fecha automaticamente cards EXECUTADO que estouraram o prazo de validação.
    finalizar_executados_vencidos(Tarefa, Comentario)

    f_data_ini = request.GET.get("data_ini") or ""
    f_data_fim = request.GET.get("data_fim") or ""
    f_user     = request.GET.get("user") or ""
    f_busca    = (request.GET.get("busca") or "").strip()
    final      = request.GET.get("final") or "hoje"

    base = Tarefa.objects.select_related("criada_por", "atribuida_para", "executor")

    if f_data_ini:
        base = base.filter(prazo__date__gte=f_data_ini)
    if f_data_fim:
        base = base.filter(prazo__date__lte=f_data_fim)

    if f_busca:
        base = base.filter(
            Q(codigo__iexact=f_busca) | Q(titulo__icontains=f_busca)
        )

    # ------------------------------------------------------------------
    # Regra de filtro de responsável (vale para TODAS as colunas):
    #   - Usuário sem permissão de gestor fica travado em si mesmo.
    #   - COM f_user (gestor filtrando alguém): mostra todos os cards
    #     em que esse usuário tem QUALQUER relação (atribuído OU
    #     executor OU criador). Filtro estrito — não mistura cards
    #     do próprio logado.
    #   - SEM f_user: mostra tudo que tem relação com o LOGADO
    #     (atribuído OU executor OU criador).
    # ------------------------------------------------------------------
    if not pode_editar(request.user):
        # Não-gestor não pode filtrar outro responsável
        f_user = str(request.user.id)

    if f_user:
        try:
            uid = int(f_user)
            base = base.filter(
                Q(atribuida_para_id=uid)
                | Q(executor_id=uid)
                | Q(criada_por_id=uid)
            ).distinct()
        except (ValueError, TypeError):
            pass
    else:
        # Gestor sem filtro: mostra tudo em que ele tem relação
        base = base.filter(
            Q(atribuida_para=request.user)
            | Q(executor=request.user)
            | Q(criada_por=request.user)
        ).distinct()

    base = _annotate_counts(base)

    abertas    = base.filter(status="aberta").order_by("-prioridade", "ordem", "-criada_em")
    executando = base.filter(status="executando").order_by("-prioridade", "-iniciado_em", "-criada_em")
    executado  = base.filter(status="executado").order_by("-prioridade", "-executado_em", "-criada_em")

    # ------------------------------------------------------------------
    # PENDENTE: espelha na tela do criador os cards aguardando validação.
    # O criador enxerga os cards que ELE criou que estão em PENDENTE
    # (devolvidos pelo executor). Cards em PENDENTE não aparecem em
    # "executando" — ficam numa coluna própria (dourado).
    # ------------------------------------------------------------------
    pendentes = base.filter(status="pendente").order_by("-pendente_em", "-criada_em")

    # Finalizadas com janela de tempo
    finalizadas = base.filter(status="feita")
    if final == "hoje":
        finalizadas = finalizadas.filter(finalizado_em__date=timezone.localdate())
    elif final == "7":
        finalizadas = finalizadas.filter(finalizado_em__gte=timezone.now() - timedelta(days=7))
    elif final == "30":
        finalizadas = finalizadas.filter(finalizado_em__gte=timezone.now() - timedelta(days=30))
    finalizadas = finalizadas.order_by("-prioridade", "-finalizado_em", "-criada_em")

    usuarios = (
        User.objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__name__in=GESTAO_CARGOS))
        .distinct()
        .order_by("username")
    )

    ctx = {
        "abertas":    abertas,
        "executando": executando,
        "executado":  executado,
        "pendentes":  pendentes,       # NOVO
        "finalizadas": finalizadas,
        "usuarios":   usuarios,
        "f_data_ini": f_data_ini,
        "f_data_fim": f_data_fim,
        "f_user":     f_user,
        "f_busca":    f_busca,         # NOVO
        "final":      final,
        "pode_criar":      pode_criar(request.user),
        "pode_editar":     pode_editar(request.user),
        "pode_deletar":    pode_deletar(request.user),
        "pode_prioridade": pode_prioridade(request.user),
        "devolucao_form":  DevolucaoForm(),   # NOVO — usado nos cards pendentes
        # URL canônica do quadro (não o endpoint /partial/cards/) para os
        # campos "next" dos cards funcionarem mesmo após o auto-refresh.
        "voltar_url": _voltar_url(request),
    }
    return ctx


@login_required
def quadro(request):
    if not tem_acesso_gestao(request.user):
        return HttpResponseForbidden("Sem acesso ao módulo Gestão.")
    return render(request, "gestao/gestao.html", _contexto_quadro(request))


@login_required
@require_GET
def partial_cards(request):
    # Mesmos dados do quadro, mas só os cards (usado no auto-refresh sem F5).
    if not tem_acesso_gestao(request.user):
        return HttpResponseForbidden("Sem acesso ao módulo Gestão.")
    return render(request, "gestao/partials/cards.html", _contexto_quadro(request))


# ============================================================
# CRUD
# ============================================================

@login_required
def criar(request):
    if not pode_criar(request.user):
        return HttpResponseForbidden("Sem permissão para criar tarefa.")
    if request.method == "POST":
        form = TarefaForm(request.POST)
        if form.is_valid():
            tarefa = form.save(commit=False)
            tarefa.criada_por = request.user
            tarefa.status = "aberta"
            tarefa.save()
            return redirect(_next_or(request, "/gestao/"))
    else:
        form = TarefaForm()
    return render(request, "gestao/tarefa_form.html", {"form": form})


@login_required
def editar(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not (pode_editar(request.user) or tarefa.criada_por_id == request.user.id):
        return HttpResponseForbidden("Sem permissão para editar.")
    if request.method == "POST":
        form = TarefaForm(request.POST, instance=tarefa)
        if form.is_valid():
            form.save()
            return redirect(_next_or(request, "/gestao/"))
    else:
        form = TarefaForm(instance=tarefa)
    return render(request, "gestao/tarefa_form.html", {"form": form, "tarefa": tarefa})


@login_required
def deletar(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_deletar(request.user):
        return HttpResponseForbidden("Somente a Diretoria (GESTAO) ou superuser pode deletar.")
    if request.method == "POST":
        tarefa.soft_delete(request.user)
        return redirect(_next_or(request, "/gestao/"))
    return render(request, "gestao/tarefa_delete.html", {"tarefa": tarefa})


# ============================================================
# DETALHE + COMENTÁRIOS + ANEXOS
# ============================================================

@login_required
def detalhe(request, pk: int):
    tarefa = get_object_or_404(
        Tarefa.objects.select_related("criada_por", "atribuida_para", "executor"), pk=pk
    )
    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para ver esta tarefa.")

    comentarios = Comentario.objects.filter(tarefa=tarefa).select_related("autor").order_by("-criado_em")
    anexos      = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")

    ctx = {
        "tarefa":       tarefa,
        "comentarios":  comentarios,
        "anexos":       anexos,
        "comentario_form":   ComentarioForm(),
        "anexo_form":        AnexoForm(),
        "devolucao_form":    DevolucaoForm(),
        "pode_editar":       pode_editar(request.user) or tarefa.criada_por_id == request.user.id,
        "pode_executar":     pode_executar(request.user, tarefa),
        "pode_marcar_executado": pode_marcar_executado(request.user, tarefa),
        "pode_finalizar":    pode_finalizar(request.user, tarefa),
        "pode_validar":      pode_validar(request.user, tarefa),
    }
    return render(request, "gestao/tarefa_detalhe.html", ctx)


@login_required
@require_POST
def comentario_criar(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")
    form = ComentarioForm(request.POST)
    if form.is_valid():
        c = form.save(commit=False)
        c.tarefa = tarefa
        c.autor  = request.user
        c.save()
    return redirect(_next_or(request, f"/gestao/detalhe/{pk}/"))


@login_required
def tarefa_anexos(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")
    anexos_qs = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")
    return render(request, "gestao/tarefa_anexos.html", {
        "tarefa": tarefa, "anexos": anexos_qs, "anexo_form": AnexoForm(),
    })


@login_required
@require_POST
def anexo_upload(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")
    form = AnexoForm(request.POST, request.FILES)
    if form.is_valid():
        a = form.save(commit=False)
        a.tarefa      = tarefa
        a.enviado_por = request.user
        a.nome_original = request.FILES["arquivo"].name if "arquivo" in request.FILES else ""
        a.save()
    return redirect(_next_or(request, f"/gestao/detalhe/{pk}/"))


@login_required
def anexo_download(request, anexo_id: int):
    anexo = get_object_or_404(Anexo.objects.select_related("tarefa"), pk=anexo_id)
    if not pode_ver_tarefa(request.user, anexo.tarefa):
        return HttpResponseForbidden("Sem permissão.")
    if not anexo.arquivo:
        raise Http404("Arquivo não encontrado.")
    try:
        return FileResponse(
            anexo.arquivo.open("rb"),
            as_attachment=True,
            filename=(anexo.nome_original or None),
        )
    except FileNotFoundError:
        raise Http404("Arquivo não encontrado.")


# ============================================================
# STATUS
# ============================================================

@login_required
@require_POST
def marcar_executando(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_executar(request.user, tarefa):
        return HttpResponseForbidden("Você não pode iniciar esta tarefa.")

    executor_real = tarefa.atribuida_para
    if tarefa.atribuida_para_id == request.user.id:
        executor_real = request.user

    tarefa.status       = "executando"
    tarefa.executor     = executor_real
    tarefa.iniciado_em  = timezone.now()
    tarefa.executado_em = None
    tarefa.pendente_em  = None
    tarefa.finalizado_em = None
    tarefa.save(update_fields=["status", "executor", "iniciado_em", "executado_em", "pendente_em", "finalizado_em"])
    return redirect(_next_or(request, "/gestao/"))


@login_required
@require_POST
def marcar_executado(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_marcar_executado(request.user, tarefa):
        return HttpResponseForbidden("Somente o executor (ou gestor) pode marcar EXECUTADO.")
    tarefa.status       = "executado"
    tarefa.executado_em = timezone.now()
    tarefa.pendente_em  = None
    tarefa.save(update_fields=["status", "executado_em", "pendente_em"])
    return redirect(_next_or(request, "/gestao/"))


@login_required
@require_POST
def devolver_pendencia(request, pk: int):
    """
    Criador analisa card EXECUTADO e devolve com pendência.
    Card vai para status PENDENTE (dourado na tela do criador).
    Exige comentário obrigatório explicando o que faltou.
    Após registrar o comentário, a view `confirmar_devolucao` move
    para EXECUTANDO de volta.

    Fluxo completo:
      EXECUTADO → [criador clica "Devolver"] → PENDENTE (dourado, tela do criador)
      PENDENTE  → [criador confirma devolução ao executor] → EXECUTANDO (laranja)
    """
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_validar(request.user, tarefa):
        return HttpResponseForbidden("Somente o criador (ou gestor) pode devolver com pendência.")

    if tarefa.status not in ("executado", "pendente"):
        return HttpResponseForbidden("Tarefa não está em estado que permite devolução.")

    form = DevolucaoForm(request.POST)
    if not form.is_valid():
        # Redireciona de volta com erro — em produção pode usar messages framework
        return redirect(_next_or(request, f"/gestao/detalhe/{pk}/"))

    # Registra comentário de devolução
    Comentario.objects.create(
        tarefa=tarefa,
        autor=request.user,
        texto=form.cleaned_data["motivo"],
        eh_devolucao=True,
    )

    # Move para PENDENTE (espelho dourado na tela do criador)
    tarefa.marcar_pendente()
    tarefa.save(update_fields=["status", "pendente_em", "finalizado_em"])

    return redirect(_next_or(request, "/gestao/"))


@login_required
@require_POST
def confirmar_devolucao(request, pk: int):
    """
    Executor refez e marca como executado novamente.
    Card sai de PENDENTE e volta para EXECUTADO para o criador validar.
    Quem age aqui é o EXECUTOR, não o criador.
    """
    tarefa = get_object_or_404(Tarefa, pk=pk)

    pode = (
        request.user.id == tarefa.executor_id
        or request.user.id == tarefa.atribuida_para_id
        or pode_editar(request.user)
    )
    if not pode:
        return HttpResponseForbidden("Sem permissão.")

    if tarefa.status != "pendente":
        return HttpResponseForbidden("Tarefa não está pendente.")

    tarefa.status       = "executado"
    tarefa.executado_em = timezone.now()
    tarefa.pendente_em  = None
    tarefa.save(update_fields=["status", "executado_em", "pendente_em"])
    return redirect(_next_or(request, "/gestao/"))


@login_required
@require_POST
def toggle_finalizado(request, pk: int):
    """
    Finaliza uma tarefa (criador ou gestor).
    Reabrir card já finalizado NÃO é feito por aqui — exige senha (view `reabrir`).
    """
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_finalizar(request.user, tarefa):
        return HttpResponseForbidden("Somente o criador (ou gestor) pode finalizar.")

    if tarefa.status == "feita":
        messages.info(request, "Tarefa já finalizada. Para reabrir, use a senha de reabertura.")
        return redirect(_next_or(request, "/gestao/"))

    tarefa.status                     = "feita"
    tarefa.finalizado_em              = timezone.now()
    tarefa.finalizado_automaticamente = False
    tarefa.save(update_fields=["status", "finalizado_em", "finalizado_automaticamente"])
    return redirect(_next_or(request, "/gestao/"))


@login_required
@require_POST
def reabrir(request, pk: int):
    """
    Reabre um card finalizado mediante senha admin (ConfiguracaoSeguranca).
    Não depende de grupo — qualquer pessoa que veja o card e saiba a senha pode
    reabri-lo. O card volta para ABERTA, zerando os carimbos de execução.
    """
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    if tarefa.status != "feita":
        messages.error(request, "Só é possível reabrir tarefas finalizadas.")
        return redirect(_next_or(request, "/gestao/"))

    senha = request.POST.get("senha") or ""
    config = ConfiguracaoSeguranca.get_solo()

    if not config.senha_reabertura:
        messages.error(request, "Senha de reabertura não configurada no admin.")
        return redirect(_next_or(request, "/gestao/"))

    if not config.check_senha(senha):
        messages.error(request, "Senha incorreta. O card continua finalizado.")
        return redirect(_next_or(request, "/gestao/"))

    tarefa.status                     = "aberta"
    tarefa.iniciado_em                = None
    tarefa.executado_em               = None
    tarefa.pendente_em                = None
    tarefa.finalizado_em              = None
    tarefa.executor                   = None
    tarefa.finalizado_automaticamente = False
    tarefa.save(update_fields=[
        "status", "iniciado_em", "executado_em", "pendente_em",
        "finalizado_em", "executor", "finalizado_automaticamente",
    ])

    Comentario.objects.create(
        tarefa=tarefa,
        autor=request.user,
        texto=f"Card reaberto por {request.user.username} mediante senha de reabertura.",
    )
    messages.success(request, f"Card {tarefa.codigo} reaberto.")
    return redirect(_next_or(request, "/gestao/"))


# ============================================================
# PRIORIDADE + REORDENAR
# ============================================================

@login_required
@require_POST
def toggle_prioridade(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_prioridade(request.user):
        return HttpResponseForbidden("Sem permissão para marcar prioridade.")
    tarefa.prioridade = not tarefa.prioridade
    tarefa.save(update_fields=["prioridade"])
    return redirect(_next_or(request, "/gestao/"))


@login_required
@require_POST
def reordenar(request):
    if not pode_editar(request.user):
        return JsonResponse({"ok": False, "error": "Sem permissão"}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        ids = payload.get("ids", [])
        if not isinstance(ids, list):
            raise ValueError
    except Exception:
        return JsonResponse({"ok": False, "error": "Payload inválido"}, status=400)

    tarefas = {t.id: t for t in Tarefa.objects.filter(id__in=ids, status="aberta")}
    ordem = 1
    for _id in ids:
        try:
            _id_int = int(_id)
        except Exception:
            continue
        t = tarefas.get(_id_int)
        if t:
            t.ordem = ordem
            ordem += 1
    Tarefa.objects.bulk_update(tarefas.values(), ["ordem"])
    return JsonResponse({"ok": True})


# ============================================================
# KPIs AO VIVO
# ============================================================

@login_required
@require_GET
def partial_kpis(request):
    if not tem_acesso_gestao(request.user):
        return HttpResponseForbidden("Sem acesso ao módulo Gestão.")

    finalizar_executados_vencidos(Tarefa, Comentario)

    base  = _build_base_filtrado(request)
    agora = timezone.now()
    status_pendentes = [Tarefa.Status.ABERTA, Tarefa.Status.EXECUTANDO, Tarefa.Status.PENDENTE]

    return render(request, "gestao/partials/kpis.html", {
        "abertas":     base.filter(status="aberta").count(),
        "executando":  base.filter(status="executando").count(),
        "executado":   base.filter(status="executado").count(),
        "pendentes":   base.filter(status="pendente").count(),    # NOVO
        "finalizadas": base.filter(status="feita").count(),
        "atrasadas":   base.filter(status__in=status_pendentes, prazo__lt=agora).count(),
        "vencendo":    base.filter(
            status__in=status_pendentes,
            prazo__gte=agora,
            prazo__lte=agora + timedelta(hours=24),
        ).count(),
        "now": agora,
    })


# ============================================================
# ALIASES (compatibilidade com urls.py existente)
# ============================================================

tarefa_criar    = criar
tarefa_editar   = editar
tarefa_deletar  = deletar
tarefa_detalhe  = detalhe

tarefa_toggle_executando  = marcar_executando
tarefa_marcar_executado   = marcar_executado
tarefa_toggle_status      = toggle_finalizado

tarefa_reordenar      = reordenar
tarefa_toggle_prioridade = toggle_prioridade

tarefa_anexos  = tarefa_anexos
anexo_upload   = anexo_upload
anexo_download = anexo_download
comentario_criar = comentario_criar