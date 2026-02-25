from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import TarefaForm, ComentarioForm, AnexoForm
from .models import Tarefa, Comentario, Anexo

User = get_user_model()

# ============================================================
# RBAC (GRUPOS) - AJUSTE AQUI SE PRECISAR
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
    """
    Editar = gestor/gestora/superuser.
    Se você usa permissão do Django (change_tarefa), mantém isso também.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    # Grupo "acima"
    if in_group(user, "GESTAO_GESTORA") or in_group(user, "GESTAO_GESTOR"):
        return True
    # fallback por perm (se você usa permissões)
    return user.has_perm("Gestao.change_tarefa") or user.has_perm("gestao.change_tarefa")


def pode_criar(user) -> bool:
    return tem_acesso_gestao(user)


def pode_prioridade(user) -> bool:
    # prioridade geralmente é gestor/gestora
    return pode_editar(user)


def pode_deletar(user) -> bool:
    # Como você pediu: só superuser ou GESTAO_GESTORA
    if not user.is_authenticated:
        return False
    return user.is_superuser or in_group(user, "GESTAO_GESTORA")


def pode_ver_tarefa(user, tarefa: Tarefa) -> bool:
    """
    Regra de visualização:
    - Gestor/gestora/superuser vê tudo
    - Usuário comum só vê se for responsável OU criador OU executor
    """
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
    """
    Marcar EXECUTANDO:
    - Gestor/gestora pode
    - Responsável (atribuída_para) pode
    """
    if not user.is_authenticated:
        return False
    return pode_editar(user) or tarefa.atribuida_para_id == user.id


def pode_marcar_executado(user, tarefa: Tarefa) -> bool:
    """
    Marcar EXECUTADO:
    - Gestor/gestora pode
    - Executor pode
    """
    if not user.is_authenticated:
        return False
    return pode_editar(user) or tarefa.executor_id == user.id


def pode_finalizar(user, tarefa: Tarefa) -> bool:
    """
    Finalizar/Reabrir:
    - Gestor/gestora pode
    - Criador pode (mantém sua lógica original)
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


# ============================================================
# QUADRO
# ============================================================

@login_required
def quadro(request):
    if not tem_acesso_gestao(request.user):
        return HttpResponseForbidden("Sem acesso ao módulo Gestão.")

    # filtros
    f_data_ini = request.GET.get("data_ini") or ""
    f_data_fim = request.GET.get("data_fim") or ""
    f_user = request.GET.get("user") or ""
    final = request.GET.get("final") or "hoje"

    base = Tarefa.objects.select_related("criada_por", "atribuida_para", "executor")

    # Se não for gestor, trava o filtro no próprio usuário
    if not pode_editar(request.user):
        f_user = str(request.user.id)

    # filtro responsável
    if f_user:
        base = base.filter(atribuida_para_id=f_user)

    # filtro prazo
    if f_data_ini:
        base = base.filter(prazo__date__gte=f_data_ini)
    if f_data_fim:
        base = base.filter(prazo__date__lte=f_data_fim)

    # segurança: usuários comuns só veem o que podem ver
    if not pode_editar(request.user):
        base = base.filter(
            Q(atribuida_para=request.user) | Q(criada_por=request.user) | Q(executor=request.user)
        )

    base = _annotate_counts(base)

    # separa colunas
    abertas = base.filter(status="aberta").order_by("-prioridade", "ordem", "-criada_em")
    executando = base.filter(status="executando").order_by("-prioridade", "-iniciado_em", "-criada_em")
    executado = base.filter(status="executado").order_by("-prioridade", "-executado_em", "-criada_em")

    # finalizadas com janela
    finalizadas = base.filter(status="feita")
    if final == "hoje":
        finalizadas = finalizadas.filter(finalizado_em__date=timezone.localdate())
    elif final == "7":
        finalizadas = finalizadas.filter(finalizado_em__gte=timezone.now() - timedelta(days=7))
    elif final == "30":
        finalizadas = finalizadas.filter(finalizado_em__gte=timezone.now() - timedelta(days=30))
    else:
        pass
    finalizadas = finalizadas.order_by("-prioridade", "-finalizado_em", "-criada_em")

    # usuários do filtro: só quem tem acesso ao Gestão
    usuarios = (
        User.objects.filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(groups__name__in=GESTAO_GROUPS)
        )
        .distinct()
        .order_by("username")
    )

    ctx = {
        "abertas": abertas,
        "executando": executando,
        "executado": executado,
        "finalizadas": finalizadas,
        "usuarios": usuarios,
        "f_data_ini": f_data_ini,
        "f_data_fim": f_data_fim,
        "f_user": f_user,
        "final": final,
        # permissões
        "pode_criar": pode_criar(request.user),
        "pode_editar": pode_editar(request.user),
        "pode_deletar": pode_deletar(request.user),
        "pode_prioridade": pode_prioridade(request.user),
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
        tarefa.delete()
        return redirect(_next_or(request, "/gestao/"))

    return render(request, "gestao/tarefa_delete.html", {"tarefa": tarefa})


# ============================================================
# DETALHE + COMENTÁRIOS + ANEXOS
# ============================================================

@login_required
def detalhe(request, pk: int):
    tarefa = get_object_or_404(Tarefa.objects.select_related("criada_por", "atribuida_para", "executor"), pk=pk)

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para ver esta tarefa.")

    comentarios = Comentario.objects.filter(tarefa=tarefa).select_related("autor").order_by("-criado_em")
    anexos = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")

    ctx = {
        "tarefa": tarefa,
        "comentarios": comentarios,
        "anexos": anexos,
        "comentario_form": ComentarioForm(),
        "anexo_form": AnexoForm(),
        "pode_editar": pode_editar(request.user) or tarefa.criada_por_id == request.user.id,
        "pode_executar": pode_executar(request.user, tarefa),
        "pode_marcar_executado": pode_marcar_executado(request.user, tarefa),
        "pode_finalizar": pode_finalizar(request.user, tarefa),
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
        c.autor = request.user
        c.save()

    return redirect(_next_or(request, f"/gestao/detalhe/{pk}/"))


@login_required
def anexos(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    anexos_qs = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")

    return render(
        request,
        "gestao/tarefa_anexos.html",
        {
            "tarefa": tarefa,
            "anexos": anexos_qs,
            "anexo_form": AnexoForm(),
        },
    )


@login_required
@require_POST
def anexo_upload(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)
    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    form = AnexoForm(request.POST, request.FILES)
    if form.is_valid():
        a = form.save(commit=False)
        a.tarefa = tarefa
        a.enviado_por = request.user
        a.nome_original = request.FILES["arquivo"].name if "arquivo" in request.FILES else ""
        a.save()

    return redirect(_next_or(request, f"/gestao/detalhe/{pk}/"))


@login_required
def anexo_download(request, pk: int):
    anexo = get_object_or_404(Anexo.objects.select_related("tarefa"), pk=pk)
    if not pode_ver_tarefa(request.user, anexo.tarefa):
        return HttpResponseForbidden("Sem permissão.")

    if not anexo.arquivo:
        raise Http404("Arquivo não encontrado.")

    try:
        return FileResponse(anexo.arquivo.open("rb"), as_attachment=False, filename=anexo.nome_original or None)
    except FileNotFoundError:
        raise Http404("Arquivo não encontrado.")


# ============================================================
# STATUS (ABERTA -> EXECUTANDO -> EXECUTADO -> FEITA)
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
def marcar_executando(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_executar(request.user, tarefa):
        return HttpResponseForbidden("Você não pode iniciar esta tarefa.")

    # ✅ regra anti-travamento:
    # - se gestor iniciar para outra pessoa, executor vira o responsável
    # - se o próprio responsável iniciar, executor é ele
    executor_real = tarefa.atribuida_para
    if tarefa.atribuida_para_id == request.user.id:
        executor_real = request.user

    tarefa.status = "executando"
    tarefa.executor = executor_real
    tarefa.iniciado_em = timezone.now()
    tarefa.executado_em = None
    tarefa.finalizado_em = None
    tarefa.save(update_fields=["status", "executor", "iniciado_em", "executado_em", "finalizado_em"])

    return redirect(_next_or(request, "/gestao/"))


@login_required
@require_POST
def marcar_executado(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_marcar_executado(request.user, tarefa):
        return HttpResponseForbidden("Somente o executor (ou gestor) pode marcar EXECUTADO.")

    tarefa.status = "executado"
    tarefa.executado_em = timezone.now()
    tarefa.save(update_fields=["status", "executado_em"])
    return redirect(_next_or(request, "/gestao/"))


@login_required
@require_POST
def toggle_finalizado(request, pk: int):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_finalizar(request.user, tarefa):
        return HttpResponseForbidden("Somente o criador (ou gestor) pode finalizar/reabrir.")

    if tarefa.status == "feita":
        # reabrir
        tarefa.status = "aberta"
        tarefa.finalizado_em = None
    else:
        tarefa.status = "feita"
        tarefa.finalizado_em = timezone.now()

    tarefa.save(update_fields=["status", "finalizado_em"])
    return redirect(_next_or(request, "/gestao/"))


# ============================================================
# REORDENAR (Sortable na coluna ABERTAS)
# ============================================================

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

    # Só reordena tarefas abertas
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
# ALIASES PARA COMPATIBILIDADE COM O urls.py (NÃO MEXER NO URLS)
# ============================================================

tarefa_criar = criar
tarefa_editar = editar
tarefa_deletar = deletar
tarefa_detalhe = detalhe

tarefa_toggle_executando = marcar_executando
tarefa_marcar_executado = marcar_executado
tarefa_toggle_status = toggle_finalizado

tarefa_reordenar = reordenar
tarefa_toggle_prioridade = toggle_prioridade

tarefa_anexos = anexos

# estes já têm o nome certo, mas garantimos compatibilidade
anexo_upload = anexo_upload
anexo_download = anexo_download
comentario_criar = comentario_criar