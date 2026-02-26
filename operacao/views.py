from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q, Max
from django.http import HttpResponseForbidden, JsonResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from core.decorators import user_in_groups
from .forms import TarefaForm, ComentarioForm, AnexoForm
from .models import Tarefa, Equipe, Comentario, Anexo


# ============================================================
# RBAC (GRUPOS)
# ============================================================

def _in_group(user, group_name: str) -> bool:
    if not user.is_authenticated:
        return False
    # se quiser, pode tirar staff daqui. mas vou manter como "admin" interno
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name=group_name).exists()


def is_coord(user) -> bool:
    return _in_group(user, "OPERACAO_CORDENACAO")


def is_supervisor(user) -> bool:
    # supervisor (limitado à equipe). coord também é "acima"
    return _in_group(user, "OPERACAO_SUPERVISOR") or is_coord(user)


def is_operador(user) -> bool:
    return _in_group(user, "OPERACAO") and (not is_supervisor(user)) and (not is_coord(user))


def membros_da_equipe_do_supervisor(user):
    """
    Retorna Users que são membros das equipes onde user é supervisor.

    Seu erro mostrou que o related_name correto NO User é:
      - operacao_equipes
    E supervisor provavelmente tem:
      - operacao_equipes_supervisionadas (no FK supervisor)
    """
    return User.objects.filter(operacao_equipes__supervisor=user).distinct()


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


def pode_mexer_tarefa(user, tarefa: Tarefa) -> bool:
    """
    Coord: pode tudo.
    Supervisor: pode tudo APENAS nas tarefas visíveis (equipe dele).
    Operador: nada (somente ações que você liberar).
    """
    if is_coord(user):
        return True
    if is_supervisor(user):
        membros = membros_da_equipe_do_supervisor(user)
        return tarefa.atribuida_para_id == user.id or tarefa.atribuida_para_id in membros.values_list("id", flat=True)
    return False


# ============================================================
# HELPERS
# ============================================================

def _inicio_hoje():
    agora = timezone.now()
    return agora.replace(hour=0, minute=0, second=0, microsecond=0)


def go_back(request, fallback="operacao:quadro"):
    nxt = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if nxt:
        return redirect(nxt)
    return redirect(fallback)


# ============================================================
# QUADRO
# ============================================================

@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def quadro(request):
    qs = queryset_visivel_para(request.user).select_related("criada_por", "atribuida_para", "executor")

    # filtros
    data_ini = (request.GET.get("data_ini") or "").strip()
    data_fim = (request.GET.get("data_fim") or "").strip()
    user_id = (request.GET.get("user") or "").strip()
    final = (request.GET.get("final") or "hoje").strip()  # hoje | 7 | 30 | tudo

    # operador não escolhe "Responsável"
    if is_operador(request.user):
        user_id = str(request.user.id)

    if user_id:
        try:
            qs = qs.filter(atribuida_para_id=int(user_id))
        except ValueError:
            pass

    if data_ini:
        qs = qs.filter(prazo__date__gte=data_ini)
    if data_fim:
        qs = qs.filter(prazo__date__lte=data_fim)

    qs = qs.annotate(
        anexos_count=Count("anexos", distinct=True),
        comentarios_count=Count("comentarios", distinct=True),
    )

    abertas = qs.filter(status="aberta").order_by("-prioridade", "ordem", "prazo", "-criada_em")
    executando = qs.filter(status="executando").order_by("-prioridade", "prazo", "-iniciado_em")
    executado = qs.filter(status="executado").order_by("-prioridade", "-executado_em", "prazo")

    # FINALIZADAS (sem atualizado_em!)
    finalizadas_qs = qs.filter(status="feita")
    agora = timezone.now()
    if final == "hoje":
        ini = _inicio_hoje()
        fim = ini + timedelta(days=1)
        finalizadas_qs = finalizadas_qs.filter(finalizado_em__gte=ini, finalizado_em__lt=fim)
    elif final in ("7", "30"):
        dias = int(final)
        finalizadas_qs = finalizadas_qs.filter(finalizado_em__gte=agora - timedelta(days=dias))
    elif final == "tudo":
        pass

    finalizadas = finalizadas_qs.order_by("-finalizado_em", "-criada_em")

    # usuários do filtro conforme cargo
    if is_coord(request.user):
        usuarios = User.objects.filter(is_active=True).order_by("username")
    elif is_supervisor(request.user):
        membros = membros_da_equipe_do_supervisor(request.user)
        usuarios = User.objects.filter(
            Q(id=request.user.id) | Q(id__in=membros.values_list("id", flat=True))
        ).distinct().order_by("username")
    else:
        usuarios = User.objects.filter(id=request.user.id)

    context = {
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
        "is_operador": is_operador(request.user),
        "is_supervisor": is_supervisor(request.user),
        "is_coord": is_coord(request.user),
    }
    return render(request, "operacao/operacao.html", context)


# ============================================================
# CRUD
# ============================================================

@user_in_groups("OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def tarefa_criar(request):
    if not (is_coord(request.user) or is_supervisor(request.user)):
        return HttpResponseForbidden("Sem permissão para criar.")

    if request.method == "POST":
        form = TarefaForm(request.POST, user=request.user)
        if form.is_valid():
            tarefa = form.save(commit=False)
            tarefa.criada_por = request.user

            # ordem: joga no final das abertas
            max_ordem = Tarefa.objects.filter(status="aberta").aggregate(m=Max("ordem"))["m"] or 0
            tarefa.ordem = max_ordem + 1
            tarefa.save()
            return go_back(request)
    else:
        form = TarefaForm(user=request.user)

    return render(request, "operacao/tarefa_form.html", {"form": form, "titulo": "Novo chamado"})


@user_in_groups("OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def tarefa_editar(request, tarefa_id: int):
    qs = Tarefa.objects.all() if is_coord(request.user) else queryset_visivel_para(request.user)
    tarefa = get_object_or_404(qs, id=tarefa_id)

    if not pode_mexer_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para editar este chamado.")

    if request.method == "POST":
        form = TarefaForm(request.POST, instance=tarefa, user=request.user)
        if form.is_valid():
            form.save()
            return go_back(request)
    else:
        form = TarefaForm(instance=tarefa, user=request.user)

    return render(request, "operacao/tarefa_form.html", {"form": form, "titulo": "Editar chamado"})


@user_in_groups("OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def tarefa_deletar(request, tarefa_id: int):
    qs = Tarefa.objects.all() if is_coord(request.user) else queryset_visivel_para(request.user)
    tarefa = get_object_or_404(qs, id=tarefa_id)

    if not pode_mexer_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para deletar este chamado.")

    if request.method == "POST":
        tarefa.delete()
        return go_back(request)

    return render(request, "operacao/tarefa_delete.html", {"tarefa": tarefa})


# ============================================================
# AÇÕES (PRIORIDADE / STATUS)
# ============================================================

@user_in_groups("OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def toggle_prioridade(request, tarefa_id: int):
    qs = Tarefa.objects.all() if is_coord(request.user) else queryset_visivel_para(request.user)
    tarefa = get_object_or_404(qs, id=tarefa_id)

    if not pode_mexer_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    tarefa.prioridade = not bool(tarefa.prioridade)
    tarefa.save(update_fields=["prioridade"])
    return go_back(request)


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def marcar_executando(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    # responsável ou gestor
    if not (request.user.id == tarefa.atribuida_para_id or is_supervisor(request.user) or is_coord(request.user)):
        return HttpResponseForbidden("Você não pode iniciar esse chamado.")

    tarefa.status = "executando"
    tarefa.executor = request.user
    if not tarefa.iniciado_em:
        tarefa.iniciado_em = timezone.now()
    tarefa.save(update_fields=["status", "executor", "iniciado_em"])
    return go_back(request)


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def marcar_executado(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    # executor ou gestor
    if not (request.user.id == tarefa.executor_id or is_supervisor(request.user) or is_coord(request.user)):
        return HttpResponseForbidden("Você não pode marcar como executado.")

    tarefa.status = "executado"
    tarefa.executado_em = timezone.now()
    tarefa.save(update_fields=["status", "executado_em"])
    return go_back(request)


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def finalizar_reabrir(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    # só criador OU coordenação
    if not (request.user.id == tarefa.criada_por_id or is_coord(request.user)):
        return HttpResponseForbidden("Somente o criador ou coordenação pode finalizar/reabrir.")

    if tarefa.status == "feita":
        tarefa.status = "aberta"
        tarefa.finalizado_em = None
        tarefa.save(update_fields=["status", "finalizado_em"])
    else:
        tarefa.status = "feita"
        tarefa.finalizado_em = timezone.now()
        tarefa.save(update_fields=["status", "finalizado_em"])

    return go_back(request)


# ============================================================
# DETALHE / COMENTÁRIOS / ANEXOS
# ============================================================

@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def detalhe(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user).select_related("criada_por", "atribuida_para", "executor"), id=tarefa_id)

    comentarios = Comentario.objects.filter(tarefa=tarefa).select_related("autor").order_by("-criado_em")
    anexos = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")

    pode_editar = is_coord(request.user) or is_supervisor(request.user)
    return render(
        request,
        "operacao/tarefa_detalhe.html",
        {
            "tarefa": tarefa,
            "comentarios": comentarios,
            "anexos": anexos,
            "comentario_form": ComentarioForm(),
            "anexo_form": AnexoForm(),
            "pode_editar": pode_editar,
            "pode_prioridade": pode_editar,
        },
    )


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
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


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def anexos(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)
    anexos_qs = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")
    return render(request, "operacao/tarefa_anexos.html", {"tarefa": tarefa, "anexos": anexos_qs, "anexo_form": AnexoForm()})


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
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


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def anexo_download(request, anexo_id: int):
    a = get_object_or_404(Anexo.objects.select_related("tarefa"), id=anexo_id)

    # segurança: só baixa se a tarefa for visível pro user
    get_object_or_404(queryset_visivel_para(request.user), id=a.tarefa_id)

    if not a.arquivo:
        raise Http404("Arquivo não encontrado.")

    return FileResponse(a.arquivo.open("rb"), as_attachment=False, filename=a.nome_original or "anexo")


# ============================================================
# REORDENAR (somente ABERTAS) - gestor
# ============================================================

@user_in_groups("OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def reordenar(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        ids = payload.get("ids", [])
        if not isinstance(ids, list):
            return JsonResponse({"ok": False, "error": "ids_invalido"}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "json_invalido"}, status=400)

    qs = Tarefa.objects.all() if is_coord(request.user) else queryset_visivel_para(request.user)
    tarefas = {t.id: t for t in qs.filter(status="aberta", id__in=ids)}

    ordem = 0
    for raw_id in ids:
        try:
            tid = int(raw_id)
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


# ============================================================
# KPIs AO VIVO (CARDS DO TOPO)
# ============================================================

@login_required
@require_GET
def partial_kpis(request):
    qs = queryset_visivel_para(request.user)

    abertas = qs.filter(status="aberta").count()
    executando = qs.filter(status="executando").count()
    executado = qs.filter(status="executado").count()
    finalizadas = qs.filter(status="feita").count()

    agora = timezone.now()
    atrasadas = qs.exclude(status="feita").filter(prazo__lt=agora).count()
    vencendo = qs.exclude(status="feita").filter(
        prazo__gte=agora,
        prazo__lte=agora + timedelta(hours=24)
    ).count()

    return render(request, "operacao/partials/kpis.html", {
        "abertas": abertas,
        "executando": executando,
        "executado": executado,
        "finalizadas": finalizadas,
        "atrasadas": atrasadas,
        "vencendo": vencendo,
        "now": timezone.now(),
    })