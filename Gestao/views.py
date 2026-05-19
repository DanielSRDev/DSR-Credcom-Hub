# Gestao/views.py
from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from .forms import TarefaForm, ComentarioForm, AnexoForm, DevolucaoForm
from .models import Tarefa, Comentario, Anexo

User = get_user_model()

# ============================================================
# RBAC
# ============================================================

GESTAO_GROUPS = ["GESTAO", "GESTAO_USUARIO", "GESTAO_GESTOR", "GESTAO_GESTORA"]


def in_group(user, group_name: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=group_name).exists()


def tem_acesso_gestao(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=GESTAO_GROUPS).exists()


def pode_editar(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if in_group(user, "GESTAO_GESTORA") or in_group(user, "GESTAO_GESTOR"):
        return True
    return user.has_perm("Gestao.change_tarefa") or user.has_perm("gestao.change_tarefa")


def pode_criar(user) -> bool:
    return tem_acesso_gestao(user)


def pode_prioridade(user) -> bool:
    return pode_editar(user)


def pode_deletar(user) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or in_group(user, "GESTAO_GESTORA")


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
    Usuário comum fica travado nas próprias tarefas.
    """
    f_data_ini = request.GET.get("data_ini") or ""
    f_data_fim = request.GET.get("data_fim") or ""
    f_user     = request.GET.get("user") or ""
    f_busca    = (request.GET.get("busca") or "").strip()

    base = Tarefa.objects.select_related("criada_por", "atribuida_para", "executor")

    if not pode_editar(request.user):
        f_user = str(request.user.id)

    if f_user:
        base = base.filter(atribuida_para_id=f_user)

    if f_data_ini:
        base = base.filter(prazo__date__gte=f_data_ini)
    if f_data_fim:
        base = base.filter(prazo__date__lte=f_data_fim)

    # Busca por código exato (ex: GES-00003) ou substring no título
    if f_busca:
        base = base.filter(
            Q(codigo__iexact=f_busca) | Q(titulo__icontains=f_busca)
        )

    if not pode_editar(request.user):
        base = base.filter(
            Q(atribuida_para=request.user)
            | Q(criada_por=request.user)
            | Q(executor=request.user)
        )

    return base


# ============================================================
# QUADRO
# ============================================================

@login_required
def quadro(request):
    if not tem_acesso_gestao(request.user):
        return HttpResponseForbidden("Sem acesso ao módulo Gestão.")

    f_data_ini = request.GET.get("data_ini") or ""
    f_data_fim = request.GET.get("data_fim") or ""
    f_user     = request.GET.get("user") or ""
    f_busca    = (request.GET.get("busca") or "").strip()
    final      = request.GET.get("final") or "hoje"

    base = Tarefa.objects.select_related("criada_por", "atribuida_para", "executor")

    if not pode_editar(request.user):
        f_user = str(request.user.id)

    if f_user:
        base = base.filter(atribuida_para_id=f_user)

    if f_data_ini:
        base = base.filter(prazo__date__gte=f_data_ini)
    if f_data_fim:
        base = base.filter(prazo__date__lte=f_data_fim)

    if f_busca:
        base = base.filter(
            Q(codigo__iexact=f_busca) | Q(titulo__icontains=f_busca)
        )

    if not pode_editar(request.user):
        base = base.filter(
            Q(atribuida_para=request.user)
            | Q(criada_por=request.user)
            | Q(executor=request.user)
        )

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
        .filter(Q(is_superuser=True) | Q(groups__name__in=GESTAO_GROUPS))
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
    }
    return render(request, "gestao/gestao.html", ctx)


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
        return HttpResponseForbidden("Somente superuser ou GESTAO_GESTORA pode deletar.")
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
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_finalizar(request.user, tarefa):
        return HttpResponseForbidden("Somente o criador (ou gestor) pode finalizar/reabrir.")

    if tarefa.status == "feita":
        tarefa.status        = "aberta"
        tarefa.finalizado_em = None
    else:
        tarefa.status        = "feita"
        tarefa.finalizado_em = timezone.now()
    tarefa.save(update_fields=["status", "finalizado_em"])
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
