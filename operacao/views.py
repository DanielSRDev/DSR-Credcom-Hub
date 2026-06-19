# operacao/views.py
from __future__ import annotations

import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q, Max
from django.http import HttpResponseForbidden, JsonResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from core.decorators import user_in_groups
from core.models import ConfiguracaoSeguranca
from core.services import finalizar_executados_vencidos
from .forms import TarefaForm, ComentarioForm, AnexoForm, DevolucaoForm
from .models import Tarefa, Equipe, Comentario, Anexo, OperacaoPermissaoUsuario


# ============================================================
# RBAC
# ============================================================

def _in_group(user, group_name: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name=group_name).exists()


def is_coord(user) -> bool:
    return _in_group(user, "OPERACAO_CORDENACAO")


def is_supervisor(user) -> bool:
    return _in_group(user, "OPERACAO_SUPERVISOR") or is_coord(user)


def is_operador(user) -> bool:
    return _in_group(user, "OPERACAO") and not is_supervisor(user) and not is_coord(user)


def membros_da_equipe_do_supervisor(user):
    return User.objects.filter(operacao_equipes__supervisores=user).distinct()


def queryset_visivel_para(user):
    """
    Cards que o usuário tem direito de ver/agir.
    Inclui SEMPRE os que ele criou — necessário para que o criador
    consiga validar (finalizar/devolver) chamados em status EXECUTADO
    ou PENDENTE, abrir detalhe, comentar e baixar anexos.
    """
    if is_coord(user):
        return Tarefa.objects.all()
    if is_supervisor(user):
        membros = membros_da_equipe_do_supervisor(user)
        return Tarefa.objects.filter(
            Q(atribuida_para__in=membros)
            | Q(atribuida_para=user)
            | Q(criada_por=user)
        ).distinct()
    return Tarefa.objects.filter(
        Q(atribuida_para=user)
        | Q(executor=user)
        | Q(criada_por=user)
    ).distinct()


def pode_mexer_tarefa(user, tarefa: Tarefa) -> bool:
    if is_coord(user):
        return True
    if is_supervisor(user):
        membros = membros_da_equipe_do_supervisor(user)
        return (
            tarefa.atribuida_para_id == user.id
            or tarefa.atribuida_para_id in membros.values_list("id", flat=True)
        )
    return False


def pode_validar(user, tarefa: Tarefa) -> bool:
    """
    Validar (devolver com pendência ou finalizar):
    - coordenação: sempre
    - supervisor: se o chamado estiver na equipe dele
    - operador: somente se for o criador
    """
    if is_coord(user):
        return True
    if is_supervisor(user):
        return pode_mexer_tarefa(user, tarefa)
    return tarefa.criada_por_id == user.id


def operador_pode_criar(user):
    if is_coord(user) or is_supervisor(user):
        return True
    if not is_operador(user):
        return False
    permissao = getattr(user, "operacao_permissao", None)
    if permissao is None:
        return True
    return permissao.pode_criar_chamado_supervisor


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


def _aplicar_filtros(qs, request):
    """
    Filtros comuns aplicados ao quadro: data, responsável e busca (título ou código).

    Regra de responsável:
      - Operador comum NÃO pode filtrar outros usuários: f_user é forçado pro próprio id.
      - Sem filtro (f_user vazio): NÃO filtra por usuário aqui — quem cuida disso é
        `queryset_visivel_para`, que já restringe ao escopo do logado (atribuído,
        executor ou criador).
      - Com filtro f_user=X: mostra TODOS os cards com qualquer relação com X
        (atribuído OU executor OU criador). Vale dentro do escopo já permitido
        pelo `queryset_visivel_para`.
    """
    data_ini = (request.GET.get("data_ini") or "").strip()
    data_fim = (request.GET.get("data_fim") or "").strip()
    user_id  = (request.GET.get("user") or "").strip()
    busca    = (request.GET.get("busca") or "").strip()

    # Operador puro fica travado em si mesmo (não escolhe outro responsável)
    if is_operador(request.user):
        user_id = str(request.user.id)

    if user_id:
        try:
            uid = int(user_id)
            qs = qs.filter(
                Q(atribuida_para_id=uid)
                | Q(executor_id=uid)
                | Q(criada_por_id=uid)
            ).distinct()
        except ValueError:
            pass

    if data_ini:
        qs = qs.filter(prazo__date__gte=data_ini)
    if data_fim:
        qs = qs.filter(prazo__date__lte=data_fim)

    if busca:
        qs = qs.filter(Q(codigo__iexact=busca) | Q(titulo__icontains=busca))

    return qs, data_ini, data_fim, user_id, busca


# ============================================================
# QUADRO
# ============================================================

@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def quadro(request):
    # Fecha automaticamente cards EXECUTADO que estouraram o prazo de validação.
    finalizar_executados_vencidos(Tarefa, Comentario)

    qs = queryset_visivel_para(request.user).select_related("criada_por", "atribuida_para", "executor")
    final = (request.GET.get("final") or "hoje").strip()

    qs, data_ini, data_fim, user_id, busca = _aplicar_filtros(qs, request)

    qs = qs.annotate(
        anexos_count=Count("anexos", distinct=True),
        comentarios_count=Count("comentarios", distinct=True),
    )

    abertas    = qs.filter(status="aberta").order_by("-prioridade", "ordem", "prazo", "-criada_em")
    executando = qs.filter(status="executando").order_by("-prioridade", "prazo", "-iniciado_em")
    executado  = qs.filter(status="executado").order_by("-prioridade", "-executado_em", "prazo")

    # PENDENTE: aparece dourado na tela de quem criou o chamado
    pendentes = qs.filter(status="pendente").order_by("-pendente_em", "-criada_em")

    finalizadas_qs = qs.filter(status="feita")
    agora = timezone.now()
    if final == "hoje":
        ini = _inicio_hoje()
        finalizadas_qs = finalizadas_qs.filter(finalizado_em__gte=ini, finalizado_em__lt=ini + timedelta(days=1))
    elif final in ("7", "30"):
        finalizadas_qs = finalizadas_qs.filter(finalizado_em__gte=agora - timedelta(days=int(final)))
    finalizadas = finalizadas_qs.order_by("-finalizado_em", "-criada_em")

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
        "abertas":    abertas,
        "executando": executando,
        "executado":  executado,
        "pendentes":  pendentes,         # NOVO
        "finalizadas": finalizadas,
        "usuarios":   usuarios,
        "f_data_ini": data_ini,
        "f_data_fim": data_fim,
        "f_user":     user_id,
        "f_busca":    busca,             # NOVO
        "final":      final,
        "pode_criar":    operador_pode_criar(request.user),
        "pode_editar":   is_coord(request.user) or is_supervisor(request.user),
        "pode_deletar":  is_coord(request.user) or is_supervisor(request.user),
        "pode_prioridade": is_coord(request.user) or is_supervisor(request.user),
        "is_operador":   is_operador(request.user),
        "is_supervisor": is_supervisor(request.user),
        "is_coord":      is_coord(request.user),
        "devolucao_form": DevolucaoForm(),   # NOVO
    }
    return render(request, "operacao/operacao.html", context)


# ============================================================
# CRUD
# ============================================================

@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def tarefa_criar(request):
    if not operador_pode_criar(request.user):
        return HttpResponseForbidden("Sem permissão para criar.")
    if request.method == "POST":
        form = TarefaForm(request.POST, user=request.user)
        if form.is_valid():
            tarefa = form.save(commit=False)
            tarefa.criada_por = request.user
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
        tarefa.soft_delete(request.user)
        return go_back(request)
    return render(request, "operacao/tarefa_delete.html", {"tarefa": tarefa})


# ============================================================
# STATUS
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
    if not (request.user.id == tarefa.atribuida_para_id or is_supervisor(request.user) or is_coord(request.user)):
        return HttpResponseForbidden("Você não pode iniciar esse chamado.")
    tarefa.status      = "executando"
    tarefa.executor    = request.user
    tarefa.pendente_em = None
    if not tarefa.iniciado_em:
        tarefa.iniciado_em = timezone.now()
    tarefa.save(update_fields=["status", "executor", "iniciado_em", "pendente_em"])
    return go_back(request)


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def marcar_executado(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)
    if not (request.user.id == tarefa.executor_id or is_supervisor(request.user) or is_coord(request.user)):
        return HttpResponseForbidden("Você não pode marcar como executado.")
    tarefa.status       = "executado"
    tarefa.executado_em = timezone.now()
    tarefa.pendente_em  = None
    tarefa.save(update_fields=["status", "executado_em", "pendente_em"])
    return go_back(request)


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def devolver_pendencia(request, tarefa_id: int):
    """
    Criador (ou supervisor/coord) devolve chamado EXECUTADO com pendência.
    Obriga comentário, move para PENDENTE (dourado).
    """
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    if not pode_validar(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para devolver este chamado.")

    if tarefa.status not in ("executado", "pendente"):
        return HttpResponseForbidden("Chamado não está em estado que permite devolução.")

    form = DevolucaoForm(request.POST)
    if not form.is_valid():
        return go_back(request)

    Comentario.objects.create(
        tarefa=tarefa,
        autor=request.user,
        texto=form.cleaned_data["motivo"],
        eh_devolucao=True,
    )

    tarefa.marcar_pendente()
    tarefa.save(update_fields=["status", "pendente_em", "finalizado_em"])
    return go_back(request)


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def confirmar_devolucao(request, tarefa_id: int):
    """
    Executor refez o trabalho e marca como executado novamente.
    Card sai de PENDENTE e volta para EXECUTADO — aparece na coluna
    de validação do criador outra vez.
    Quem age aqui é o EXECUTOR, não o criador.
    """
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    pode = (
        request.user.id == tarefa.executor_id
        or request.user.id == tarefa.atribuida_para_id
        or is_supervisor(request.user)
        or is_coord(request.user)
    )
    if not pode:
        return HttpResponseForbidden("Sem permissão.")

    if tarefa.status != "pendente":
        return HttpResponseForbidden("Chamado não está pendente.")

    tarefa.status       = "executado"
    tarefa.executado_em = timezone.now()
    tarefa.pendente_em  = None
    tarefa.save(update_fields=["status", "executado_em", "pendente_em"])
    return go_back(request)


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def finalizar_reabrir(request, tarefa_id: int):
    """
    Finaliza um chamado (criador ou coordenação).
    Reabrir card já finalizado NÃO é feito por aqui — exige senha (view `reabrir`).
    """
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)
    if not (request.user.id == tarefa.criada_por_id or is_coord(request.user)):
        return HttpResponseForbidden("Somente o criador ou coordenação pode finalizar.")
    if tarefa.status == "feita":
        messages.info(request, "Chamado já finalizado. Para reabrir, use a senha de reabertura.")
        return go_back(request)
    tarefa.status                     = "feita"
    tarefa.finalizado_em              = timezone.now()
    tarefa.finalizado_automaticamente = False
    tarefa.save(update_fields=["status", "finalizado_em", "finalizado_automaticamente"])
    return go_back(request)


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def reabrir(request, tarefa_id: int):
    """
    Reabre um card finalizado mediante senha admin (ConfiguracaoSeguranca).
    Não depende de grupo — qualquer pessoa que enxergue o card e saiba a senha
    pode reabri-lo. O card volta para ABERTA, zerando os carimbos de execução.
    """
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)

    if tarefa.status != "feita":
        messages.error(request, "Só é possível reabrir cards finalizados.")
        return go_back(request)

    senha = request.POST.get("senha") or ""
    config = ConfiguracaoSeguranca.get_solo()

    if not config.senha_reabertura:
        messages.error(request, "Senha de reabertura não configurada no admin.")
        return go_back(request)

    if not config.check_senha(senha):
        messages.error(request, "Senha incorreta. O card continua finalizado.")
        return go_back(request)

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
    return go_back(request)


# ============================================================
# DETALHE / COMENTÁRIOS / ANEXOS
# ============================================================

@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def detalhe(request, tarefa_id: int):
    tarefa = get_object_or_404(
        queryset_visivel_para(request.user).select_related("criada_por", "atribuida_para", "executor"),
        id=tarefa_id,
    )
    comentarios = Comentario.objects.filter(tarefa=tarefa).select_related("autor").order_by("-criado_em")
    anexos      = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")
    pode_editar_flag = is_coord(request.user) or is_supervisor(request.user)

    return render(request, "operacao/tarefa_detalhe.html", {
        "tarefa":         tarefa,
        "comentarios":    comentarios,
        "anexos":         anexos,
        "comentario_form": ComentarioForm(),
        "anexo_form":      AnexoForm(),
        "devolucao_form":  DevolucaoForm(),
        "pode_editar":     pode_editar_flag,
        "pode_prioridade": pode_editar_flag,
        "pode_validar":    pode_validar(request.user, tarefa),
    })


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def comentario_criar(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)
    form = ComentarioForm(request.POST)
    if form.is_valid():
        c = form.save(commit=False)
        c.tarefa = tarefa
        c.autor  = request.user
        c.save()
    return go_back(request, fallback="operacao:detalhe")


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def anexos(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)
    anexos_qs = Anexo.objects.filter(tarefa=tarefa).select_related("enviado_por").order_by("-enviado_em")
    return render(request, "operacao/tarefa_anexos.html", {
        "tarefa": tarefa, "anexos": anexos_qs, "anexo_form": AnexoForm(),
    })


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
@require_POST
def anexo_upload(request, tarefa_id: int):
    tarefa = get_object_or_404(queryset_visivel_para(request.user), id=tarefa_id)
    form = AnexoForm(request.POST, request.FILES)
    if form.is_valid():
        a = form.save(commit=False)
        a.tarefa      = tarefa
        a.enviado_por = request.user
        if not a.nome_original and a.arquivo:
            a.nome_original = a.arquivo.name
        a.save()
    return go_back(request, fallback="operacao:anexos")


@user_in_groups("OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO")
@login_required
def anexo_download(request, anexo_id: int):
    a = get_object_or_404(Anexo.objects.select_related("tarefa"), id=anexo_id)
    get_object_or_404(queryset_visivel_para(request.user), id=a.tarefa_id)
    if not a.arquivo:
        raise Http404("Arquivo não encontrado.")
    return FileResponse(a.arquivo.open("rb"), as_attachment=False, filename=a.nome_original or "anexo")


# ============================================================
# REORDENAR — usa bulk_update (alinhado com Gestao)
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

    ordem = 1
    for raw_id in ids:
        try:
            tid = int(raw_id)
        except Exception:
            continue
        t = tarefas.get(tid)
        if t:
            t.ordem = ordem
            ordem += 1

    # bulk_update — única query (corrigido vs versão anterior)
    Tarefa.objects.bulk_update(tarefas.values(), ["ordem"])
    return JsonResponse({"ok": True})


# ============================================================
# KPIs AO VIVO
# ============================================================

@login_required
@require_GET
def partial_kpis(request):
    finalizar_executados_vencidos(Tarefa, Comentario)

    qs    = queryset_visivel_para(request.user)
    agora = timezone.now()
    status_pendentes = [Tarefa.Status.ABERTA, Tarefa.Status.EXECUTANDO, Tarefa.Status.PENDENTE]

    return render(request, "operacao/partials/kpis.html", {
        "abertas":     qs.filter(status="aberta").count(),
        "executando":  qs.filter(status="executando").count(),
        "executado":   qs.filter(status="executado").count(),
        "pendentes":   qs.filter(status="pendente").count(),     # NOVO
        "finalizadas": qs.filter(status="feita").count(),
        "atrasadas":   qs.filter(status__in=status_pendentes, prazo__lt=agora).count(),
        "vencendo":    qs.filter(
            status__in=status_pendentes,
            prazo__gte=agora,
            prazo__lte=agora + timedelta(hours=24),
        ).count(),
        "now": agora,
    })