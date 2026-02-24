from __future__ import annotations

import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Max
from django.http import Http404, HttpResponseForbidden, JsonResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import TarefaForm, ComentarioForm, AnexoForm
from .models import Tarefa, Equipe, Comentario, Anexo
from core.decorators import user_in_groups

User = get_user_model()

operacao_required = user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")


def _in_group(user, name: str) -> bool:
    return user.is_authenticated and user.groups.filter(name=name).exists()


def is_coord(user) -> bool:
    return user.is_authenticated and (user.is_superuser or user.is_staff or _in_group(user, "OPERACAO_CORDENACAO"))


def is_supervisor(user) -> bool:
    return user.is_authenticated and (_in_group(user, "OPERACAO_SUPERVISOR") or is_coord(user))


def is_operador(user) -> bool:
    return user.is_authenticated and _in_group(user, "OPERACAO") and (not is_supervisor(user)) and (not is_coord(user))


def equipes_do_supervisor(user):
    return Equipe.objects.filter(supervisor=user, ativa=True)


def membros_da_equipe_do_supervisor(user):
    # usuários que pertencem às equipes que esse supervisor supervisiona
    return User.objects.filter(equipes_membro__supervisor=user, equipes_membro__ativa=True).distinct()


def queryset_visivel_para(user):
    """
    Coordenação: vê tudo.
    Supervisor: vê tarefas atribuídas aos membros da equipe dele (e ele mesmo).
    Operador: vê somente tarefas atribuídas a ele.
    """
    if is_coord(user):
        return Tarefa.objects.all()

    if is_supervisor(user):
        membros = membros_da_equipe_do_supervisor(user)
        return Tarefa.objects.filter(Q(atribuida_para__in=membros) | Q(atribuida_para=user)).distinct()

    return Tarefa.objects.filter(atribuida_para=user)


def pode_gerenciar_tarefa(user, tarefa: Tarefa) -> bool:
    """
    Supervisor só pode gerenciar (criar/editar/deletar/prioridade) tarefas
    que pertençam ao escopo da(s) equipe(s) dele.
    Coordenação pode tudo.
    """
    if is_coord(user):
        return True
    if not is_supervisor(user):
        return False

    membros = membros_da_equipe_do_supervisor(user)
    return tarefa.atribuida_para_id == user.id or membros.filter(id=tarefa.atribuida_para_id).exists()


def go_back(request, fallback="operacao:quadro"):
    nxt = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if nxt:
        return redirect(nxt)
    return redirect(fallback)


# ============================================================
# QUADRO
# ============================================================
@login_required
@operacao_required
def quadro(request):
    qs = queryset_visivel_para(request.user).select_related("criada_por", "atribuida_para", "executor")

    data_ini = (request.GET.get("data_ini") or "").strip()
    data_fim = (request.GET.get("data_fim") or "").strip()
    user_id = (request.GET.get("user") or "").strip()
    final = (request.GET.get("final") or "hoje").strip()

    # Se não for coord/supervisor, trava filtro no próprio usuário
    if not (is_coord(request.user) or is_supervisor(request.user)):
        user_id = str(request.user.id)

    if user_id:
        qs = qs.filter(atribuida_para_id=user_id)

    if data_ini:
        qs = qs.filter(prazo__date__gte=data_ini)
    if data_fim:
        qs = qs.filter(prazo__date__lte=data_fim)

    qs = qs.annotate(
        anexos_count=Count("anexos", distinct=True),
        comentarios_count=Count("comentarios", distinct=True),
    )

    agora = timezone.now()
    abertas = qs.filter(status="aberta").order_by("-prioridade", "ordem", "prazo")
    executando = qs.filter(status="executando").order_by("-prioridade", "prazo")
    executado = qs.filter(status="executado").order_by("-prioridade", "-executado_em", "prazo")

    finalizadas_qs = qs.filter(status="feita")
    if final == "hoje":
        ini = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        fim = ini + timedelta(days=1)
        finalizadas_qs = finalizadas_qs.filter(finalizado_em__gte=ini, finalizado_em__lt=fim)
    elif final in ("7", "30"):
        dias = int(final)
        finalizadas_qs = finalizadas_qs.filter(finalizado_em__gte=agora - timedelta(days=dias))
    elif final == "tudo":
        pass

    finalizadas = finalizadas_qs.order_by("-finalizado_em")

    # usuários para filtro
    if is_coord(request.user):
        usuarios = User.objects.all().order_by("username")
    elif is_supervisor(request.user):
        usuarios = (membros_da_equipe_do_supervisor(request.user) | User.objects.filter(id=request.user.id)).distinct().order_by("username")
    else:
        usuarios = User.objects.filter(id=request.user.id)

    return render(
        request,
        "operacao/operacao.html",
        {
            "abertas": abertas,
            "executando": executando,
            "executado": executado,
            "finalizadas": finalizadas,
            "usuarios": usuarios,
            "f_data_ini": data_ini,
            "f_data_fim": data_fim,
            "f_user": user_id,
            "final": final,
            "pode_criar": is_coord(request.user) or is_supervisor(request.user),
            "pode_editar": is_coord(request.user) or is_supervisor(request.user),
            "pode_deletar": is_coord(request.user) or is_supervisor(request.user),
            "pode_prioridade": is_coord(request.user) or is_supervisor(request.user),
        },
    )


# ============================================================
# CRIAR
# ============================================================
@login_required
@operacao_required
def criar(request):
    if not (is_coord(request.user) or is_supervisor(request.user)):
        return HttpResponseForbidden("Sem permissão para criar chamado.")

    if request.method == "POST":
        form = TarefaForm(request.POST, user=request.user, is_coord=is_coord(request.user), is_supervisor=is_supervisor(request.user))
        if form.is_valid():
            tarefa = form.save(commit=False)
            tarefa.criada_por = request.user

            max_ordem = Tarefa.objects.filter(status="aberta").aggregate(m=Max("ordem"))["m"] or 0
            tarefa.ordem = max_ordem + 1

            tarefa.save()

            messages.success(request, "Chamado criado.")
            return go_back(request)
    else:
        form = TarefaForm(user=request.user, is_coord=is_coord(request.user), is_supervisor=is_supervisor(request.user))

    return render(request, "operacao/tarefa_form.html", {"form": form, "titulo": "Novo chamado"})


# ============================================================
# EDITAR / DELETAR
# ============================================================
@login_required
@operacao_required
def editar(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    if not pode_gerenciar_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para editar este chamado.")

    if request.method == "POST":
        form = TarefaForm(request.POST, instance=tarefa, user=request.user, is_coord=is_coord(request.user), is_supervisor=is_supervisor(request.user))
        if form.is_valid():
            form.save()
            messages.success(request, "Chamado atualizado.")
            return go_back(request)
    else:
        form = TarefaForm(instance=tarefa, user=request.user, is_coord=is_coord(request.user), is_supervisor=is_supervisor(request.user))

    return render(request, "operacao/tarefa_form.html", {"form": form, "titulo": "Editar chamado"})


@login_required
@operacao_required
def deletar(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    if not pode_gerenciar_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para deletar este chamado.")

    if request.method == "POST":
        tarefa.delete()
        messages.success(request, "Chamado deletado.")
        return go_back(request)

    return render(request, "operacao/tarefa_delete.html", {"tarefa": tarefa})


# ============================================================
# PRIORIDADE
# ============================================================
@login_required
@operacao_required
@require_POST
def prioridade(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    if not pode_gerenciar_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para prioridade.")

    tarefa.prioridade = not bool(tarefa.prioridade)
    tarefa.save(update_fields=["prioridade"])
    return go_back(request)


# ============================================================
# STATUS
# ============================================================
@login_required
@operacao_required
@require_POST
def executando(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    if not (request.user.id == tarefa.atribuida_para_id or is_supervisor(request.user) or is_coord(request.user)):
        return HttpResponseForbidden("Você não pode iniciar esse chamado.")

    tarefa.status = "executando"
    tarefa.executor = request.user
    if not tarefa.iniciado_em:
        tarefa.iniciado_em = timezone.now()
    tarefa.save(update_fields=["status", "executor", "iniciado_em"])
    return go_back(request)


@login_required
@operacao_required
@require_POST
def executado(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    if not (request.user.id == tarefa.executor_id or is_supervisor(request.user) or is_coord(request.user)):
        return HttpResponseForbidden("Você não pode marcar como executado.")

    tarefa.status = "executado"
    tarefa.executado_em = timezone.now()
    tarefa.save(update_fields=["status", "executado_em"])
    return go_back(request)


@login_required
@operacao_required
@require_POST
def toggle(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    # só criador ou coordenação finaliza/reabre
    if not (request.user.id == tarefa.criada_por_id or is_coord(request.user)):
        return HttpResponseForbidden("Somente o criador ou coordenação pode finalizar/reabrir.")

    if tarefa.status == "feita":
        tarefa.status = "aberta"
        tarefa.finalizado_em = None
    else:
        tarefa.status = "feita"
        tarefa.finalizado_em = timezone.now()

    tarefa.save(update_fields=["status", "finalizado_em"])
    return go_back(request)


# ============================================================
# DETALHE / ANEXOS / COMENTÁRIOS
# ============================================================
@login_required
@operacao_required
def detalhe(request, tarefa_id: int):
    tarefa = get_object_or_404(
        queryset_visivel_para(request.user).select_related("criada_por", "atribuida_para", "executor"),
        id=tarefa_id,
    )

    comentarios = Comentario.objects.filter(tarefa=tarefa).select_related("autor").order_by("-criado_em")
    anexos = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")

    pode_editar_flag = pode_gerenciar_tarefa(request.user, tarefa)
    pode_executar_flag = (request.user.id == tarefa.atribuida_para_id) or pode_editar_flag
    pode_marcar_executado_flag = (request.user.id == tarefa.executor_id) or pode_editar_flag
    pode_finalizar_flag = (request.user.id == tarefa.criada_por_id) or is_coord(request.user)

    return render(
        request,
        "operacao/tarefa_detalhe.html",
        {
            "tarefa": tarefa,
            "comentarios": comentarios,
            "anexos": anexos,
            "comentario_form": ComentarioForm(),
            "anexo_form": AnexoForm(),
            "pode_editar": pode_editar_flag,
            "pode_executar": pode_executar_flag,
            "pode_marcar_executado": pode_marcar_executado_flag,
            "pode_finalizar": pode_finalizar_flag,
        },
    )


@login_required
@operacao_required
@require_POST
def comentario_criar(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    form = ComentarioForm(request.POST)
    if form.is_valid():
        c = form.save(commit=False)
        c.tarefa = tarefa
        c.autor = request.user
        c.save()

    return go_back(request, fallback="operacao:detalhe")


@login_required
@operacao_required
def anexos(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)
    anexos_qs = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")
    return render(request, "operacao/tarefa_anexos.html", {"tarefa": tarefa, "anexos": anexos_qs, "anexo_form": AnexoForm()})


@login_required
@operacao_required
@require_POST
def anexo_upload(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    form = AnexoForm(request.POST, request.FILES)
    if form.is_valid():
        a = form.save(commit=False)
        a.tarefa = tarefa
        a.enviado_por = request.user
        if not a.nome_original and a.arquivo:
            a.nome_original = a.arquivo.name
        a.save()

    return go_back(request, fallback="operacao:anexos")


@login_required
@operacao_required
def anexo_download(request, anexo_id: int):
    a = get_object_or_404(Anexo.objects.select_related("tarefa"), id=anexo_id)

    # segurança: só baixa se a tarefa for visível
    get_object_or_404(queryset_visivel_para(request.user), id=a.tarefa_id)

    return FileResponse(a.arquivo.open("rb"), as_attachment=False, filename=a.nome_original or None)


# ============================================================
# REORDENAR
# ============================================================
@login_required
@operacao_required
@require_POST
def reordenar(request):
    if not (is_coord(request.user) or is_supervisor(request.user)):
        return JsonResponse({"ok": False, "error": "sem_permissao"}, status=403)

    payload = json.loads(request.body.decode("utf-8"))
    ids = payload.get("ids", [])

    qs = queryset_visivel_para(request.user)
    tarefas = {t.id: t for t in qs.filter(status="aberta", id__in=ids)}

    ordem = 0
    for raw in ids:
        try:
            tid = int(raw)
        except Exception:
            continue
        t = tarefas.get(tid)
        if not t:
            continue
        ordem += 1
        if t.ordem != ordem:
            t.ordem = ordem
            t.save(update_fields=["ordem"])

    return JsonResponse({"ok": True})