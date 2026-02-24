import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Max, Count
from django.http import JsonResponse, HttpResponseForbidden, FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .forms import TarefaForm, AnexoForm, ComentarioForm
from .models import Tarefa, Anexo, Comentario
from core.decorators import user_in_groups

User = get_user_model()

# -------------------------
# Decorator do módulo
# -------------------------
gestao_required = user_in_groups("GESTAO", "GESTAO_GESTOR", "GESTAO_GESTORA", "GESTAO_USUARIO")


def go_back(request, fallback="gestao:quadro"):
    nxt = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if nxt:
        return redirect(nxt)
    return redirect(fallback)


def inicio_do_dia(dt):
    dt = timezone.localtime(dt)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


# -------------------------
# Permissões (Gestão)
# -------------------------
def pode_criar(user) -> bool:
    return user.is_authenticated and user.has_perm("Gestao.add_tarefa")


def pode_editar(user) -> bool:
    return user.is_authenticated and user.has_perm("Gestao.change_tarefa")


def pode_deletar(user) -> bool:
    # mantém como você já tinha: só superuser
    return user.is_authenticated and user.is_superuser


def pode_prioridade(user) -> bool:
    return user.is_authenticated and user.is_superuser


def pode_ver_tarefa(user, tarefa: Tarefa) -> bool:
    if pode_editar(user):
        return True
    if not user.is_authenticated:
        return False
    return (
        tarefa.atribuida_para_id == user.id
        or tarefa.criada_por_id == user.id
        or tarefa.executor_id == user.id
    )


def pode_anexar(user, tarefa: Tarefa) -> bool:
    return pode_ver_tarefa(user, tarefa)


def pode_executar(user, tarefa: Tarefa) -> bool:
    if pode_editar(user):
        return True
    return user.is_authenticated and tarefa.atribuida_para_id == user.id


def pode_marcar_executado(user, tarefa: Tarefa) -> bool:
    if pode_editar(user):
        return True
    return user.is_authenticated and tarefa.executor_id == user.id


def pode_finalizar(user, tarefa: Tarefa) -> bool:
    if pode_editar(user):
        return True
    return user.is_authenticated and tarefa.criada_por_id == user.id


# ============================================================
# QUADRO
# ============================================================
@login_required
@gestao_required
def quadro(request):
    qs = Tarefa.objects.all()

    # quem não é gestor não vê tudo
    if not pode_editar(request.user):
        qs = qs.filter(
            models.Q(atribuida_para=request.user)
            | models.Q(criada_por=request.user)
            | models.Q(executor=request.user)
        )

    f_data_ini = (request.GET.get("data_ini") or "").strip()
    f_data_fim = (request.GET.get("data_fim") or "").strip()
    f_user = (request.GET.get("user") or "").strip()

    d_ini = parse_date(f_data_ini) if f_data_ini else None
    d_fim = parse_date(f_data_fim) if f_data_fim else None

    if d_ini:
        qs = qs.filter(prazo__date__gte=d_ini)
    if d_fim:
        qs = qs.filter(prazo__date__lte=d_fim)

    if f_user:
        try:
            f_user_id = int(f_user)
        except ValueError:
            f_user_id = None

        if f_user_id:
            if pode_editar(request.user):
                qs = qs.filter(atribuida_para_id=f_user_id)
            else:
                qs = qs.filter(atribuida_para=request.user)

    qs = qs.annotate(
        anexos_count=Count("anexos", distinct=True),
        comentarios_count=Count("comentarios", distinct=True),
    )

    abertas = qs.filter(status=Tarefa.Status.ABERTA).order_by("-prioridade", "ordem", "prazo")
    executando = qs.filter(status=Tarefa.Status.EXECUTANDO).order_by("-prioridade", "prazo")
    executado = qs.filter(status=Tarefa.Status.EXECUTADO).order_by("-prioridade", "-executado_em", "prazo")

    final = (request.GET.get("final") or "hoje").strip()
    agora = timezone.now()
    inicio_hoje = inicio_do_dia(agora)

    finalizadas = qs.filter(status=Tarefa.Status.FEITA).order_by("-finalizado_em", "-atualizado_em")
    if final == "hoje":
        finalizadas = finalizadas.filter(finalizado_em__gte=inicio_hoje)
    elif final == "7":
        finalizadas = finalizadas.filter(finalizado_em__gte=agora - timedelta(days=7))
    elif final == "30":
        finalizadas = finalizadas.filter(finalizado_em__gte=agora - timedelta(days=30))

    usuarios = User.objects.filter(is_active=True).order_by("username")

    return render(
        request,
        "Gestao/Gestao.html",
        {
            "abertas": abertas,
            "executando": executando,
            "executado": executado,
            "finalizadas": finalizadas,
            "final": final,
            "agora": agora,
            "usuarios": usuarios,
            "f_data_ini": f_data_ini,
            "f_data_fim": f_data_fim,
            "f_user": f_user,
            "pode_criar": pode_criar(request.user),
            "pode_editar": pode_editar(request.user),
            "pode_deletar": pode_deletar(request.user),
            "pode_prioridade": pode_prioridade(request.user),
        },
    )


# ============================================================
# CRIAR
# ============================================================
@login_required
@gestao_required
def tarefa_criar(request):
    if not pode_criar(request.user):
        return HttpResponseForbidden("Sem permissão para criar tarefas.")

    if request.method == "POST":
        form = TarefaForm(request.POST)
        if form.is_valid():
            tarefa = form.save(commit=False)
            tarefa.criada_por = request.user

            max_ordem = Tarefa.objects.filter(status=Tarefa.Status.ABERTA).aggregate(m=Max("ordem"))["m"] or 0
            tarefa.ordem = max_ordem + 1
            tarefa.save()

            messages.success(request, "Tarefa criada.")
            return go_back(request)
    else:
        form = TarefaForm()

    return render(request, "Gestao/tarefa_form.html", {"form": form, "modo": "Criar"})


@login_required
@gestao_required
def tarefa_editar(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_editar(request.user):
        return HttpResponseForbidden("Sem permissão para editar tarefas.")

    if request.method == "POST":
        form = TarefaForm(request.POST, instance=tarefa)
        if form.is_valid():
            form.save()
            messages.success(request, "Tarefa atualizada.")
            return go_back(request)
    else:
        form = TarefaForm(instance=tarefa)

    return render(request, "Gestao/tarefa_form.html", {"form": form, "modo": "Editar", "tarefa": tarefa})


@login_required
@gestao_required
def tarefa_detalhe(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    comentarios = tarefa.comentarios.all()
    anexos = tarefa.anexos.all().order_by("-enviado_em")

    return render(
        request,
        "Gestao/tarefa_detalhe.html",
        {
            "tarefa": tarefa,
            "comentarios": comentarios,
            "anexos": anexos,
            "comentario_form": ComentarioForm(),
            "anexo_form": AnexoForm(),
            "pode_editar": pode_editar(request.user),
            "pode_prioridade": pode_prioridade(request.user),
            "pode_executar": pode_executar(request.user, tarefa),
            "pode_marcar_executado": pode_marcar_executado(request.user, tarefa),
            "pode_finalizar": pode_finalizar(request.user, tarefa),
        },
    )


@login_required
@gestao_required
def tarefa_deletar(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_deletar(request.user):
        return HttpResponseForbidden("Apenas superuser pode deletar tarefas.")

    if request.method == "POST":
        tarefa.delete()
        messages.success(request, "Tarefa deletada.")
        return go_back(request)

    return render(request, "Gestao/tarefa_delete.html", {"tarefa": tarefa})


@login_required
@gestao_required
@require_POST
def tarefa_toggle_status(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_finalizar(request.user, tarefa):
        return HttpResponseForbidden("Somente quem criou pode finalizar/reabrir.")

    if tarefa.status == Tarefa.Status.FEITA:
        tarefa.reabrir()
        tarefa.save(update_fields=["status", "executor", "iniciado_em", "executado_em", "finalizado_em", "atualizado_em"])
    else:
        tarefa.finalizar()
        tarefa.save(update_fields=["status", "finalizado_em", "atualizado_em"])

    return go_back(request)


@login_required
@gestao_required
@require_POST
def tarefa_toggle_executando(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_executar(request.user, tarefa):
        return HttpResponseForbidden("Somente o responsável pode marcar como executando.")

    if tarefa.status == Tarefa.Status.EXECUTANDO:
        tarefa.status = Tarefa.Status.ABERTA
        tarefa.save(update_fields=["status", "atualizado_em"])
    else:
        tarefa.iniciar_execucao(user=request.user)
        tarefa.save(update_fields=["status", "executor", "iniciado_em", "executado_em", "finalizado_em", "atualizado_em"])

    return go_back(request)


@login_required
@gestao_required
@require_POST
def tarefa_marcar_executado(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_marcar_executado(request.user, tarefa):
        return HttpResponseForbidden("Somente o executor pode marcar como executado.")

    if tarefa.status != Tarefa.Status.FEITA:
        tarefa.marcar_executado()
        tarefa.save(update_fields=["status", "executado_em", "atualizado_em"])

    return go_back(request)


@login_required
@gestao_required
@require_POST
def tarefa_reordenar(request):
    if not pode_editar(request.user):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    payload = json.loads(request.body.decode("utf-8"))
    ids = payload.get("ids", [])

    for i, tid in enumerate(ids, start=1):
        Tarefa.objects.filter(id=tid, status=Tarefa.Status.ABERTA).update(ordem=i)

    return JsonResponse({"ok": True})


@login_required
@gestao_required
@require_POST
def tarefa_toggle_prioridade(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_prioridade(request.user):
        return HttpResponseForbidden("Apenas superuser pode alterar prioridade.")

    tarefa.prioridade = not bool(tarefa.prioridade)
    tarefa.save(update_fields=["prioridade", "atualizado_em"])
    return go_back(request)


@login_required
@gestao_required
def tarefa_anexos(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    anexos = tarefa.anexos.all().order_by("-enviado_em")
    return render(request, "Gestao/tarefa_anexos.html", {"tarefa": tarefa, "anexos": anexos, "anexo_form": AnexoForm()})


@login_required
@gestao_required
@require_POST
def anexo_upload(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_anexar(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para anexar.")

    form = AnexoForm(request.POST, request.FILES)
    if form.is_valid():
        a = form.save(commit=False)
        a.tarefa = tarefa
        a.enviado_por = request.user
        a.save()
        messages.success(request, "Anexo enviado.")
    else:
        messages.error(request, "Falha ao enviar anexo.")

    return go_back(request)


@login_required
@gestao_required
def anexo_download(request, anexo_id):
    anexo = get_object_or_404(Anexo, pk=anexo_id)
    tarefa = anexo.tarefa

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    if not anexo.arquivo:
        raise Http404("Arquivo não encontrado.")

    return FileResponse(anexo.arquivo.open("rb"), as_attachment=False, filename=anexo.nome_original or "anexo")


@login_required
@gestao_required
@require_POST
def comentario_criar(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    form = ComentarioForm(request.POST)
    if form.is_valid():
        c = form.save(commit=False)
        c.tarefa = tarefa
        c.autor = request.user
        c.save()
        messages.success(request, "Comentário registrado.")
    else:
        messages.error(request, "Falha ao registrar comentário.")

    return go_back(request)