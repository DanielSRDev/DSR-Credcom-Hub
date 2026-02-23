# Gestao/views.py
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Max, Count
from django.http import JsonResponse, HttpResponseForbidden, FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import TarefaForm, AnexoForm, ComentarioForm
from .models import Tarefa, Anexo

User = get_user_model()


# -------------------------
# Helpers
# -------------------------
def app_label():
    # evita treta de app_label maiúsculo/minúsculo
    return Tarefa._meta.app_label


def pode_criar(user) -> bool:
    return user.is_authenticated and user.has_perm(f"{app_label()}.add_tarefa")


def pode_editar(user) -> bool:
    return user.is_authenticated and user.has_perm(f"{app_label()}.change_tarefa")


def pode_deletar(user) -> bool:
    return user.is_authenticated and user.is_superuser


def pode_prioridade(user) -> bool:
    return user.is_authenticated and user.is_superuser


def pode_ver_tarefa(user, tarefa: Tarefa) -> bool:
    return pode_editar(user) or (user.is_authenticated and tarefa.atribuida_para_id == user.id)


def pode_anexar(user, tarefa: Tarefa) -> bool:
    return pode_editar(user) or (user.is_authenticated and tarefa.atribuida_para_id == user.id)


def safe_next_url(request, fallback_name="gestao:quadro"):
    nxt = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return None


def go_back(request, fallback_name="gestao:quadro"):
    nxt = safe_next_url(request, fallback_name=fallback_name)
    if nxt:
        return redirect(nxt)
    return redirect(fallback_name)


# ============================================================
# QUADRO
# ============================================================
@login_required
def quadro(request):
    qs = Tarefa.objects.all()

    if not pode_editar(request.user):
        qs = qs.filter(atribuida_para=request.user)

    # filtros
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

    # ordenação
    abertas = qs.filter(status=Tarefa.Status.ABERTA).order_by("-prioridade", "ordem", "prazo")
    executando = qs.filter(status=Tarefa.Status.EXECUTANDO).order_by("-prioridade", "iniciado_em", "prazo")
    feitas = qs.filter(status=Tarefa.Status.FEITA).order_by("-prioridade", "-finalizado_em", "-atualizado_em")

    usuarios = User.objects.filter(is_active=True).order_by("username")

    return render(
        request,
        "Gestao/Gestao.html",
        {
            "abertas": abertas,
            "executando": executando,
            "feitas": feitas,
            "agora": timezone.now(),
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
# DETALHE
# ============================================================
@login_required
def tarefa_detalhe(request, pk):
    tarefa = get_object_or_404(
        Tarefa.objects.annotate(
            anexos_count=Count("anexos", distinct=True),
            comentarios_count=Count("comentarios", distinct=True),
        ),
        pk=pk,
    )

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    anexos = tarefa.anexos.all().order_by("-enviado_em")
    comentarios = tarefa.comentarios.select_related("autor").all()
    comentario_form = ComentarioForm()
    anexo_form = AnexoForm()

    return render(
        request,
        "Gestao/tarefa_detalhe.html",
        {
            "tarefa": tarefa,
            "anexos": anexos,
            "comentarios": comentarios,
            "comentario_form": comentario_form,
            "anexo_form": anexo_form,
            "pode_editar": pode_editar(request.user),
            "pode_deletar": pode_deletar(request.user),
            "pode_prioridade": pode_prioridade(request.user),
        },
    )


# ============================================================
# CRIAR
# ============================================================
@login_required
def tarefa_criar(request):
    if not pode_criar(request.user):
        return HttpResponseForbidden("Sem permissão para criar tarefas.")

    if request.method == "POST":
        form = TarefaForm(request.POST)
        if form.is_valid():
            tarefa = form.save(commit=False)
            tarefa.criada_por = request.user

            max_ordem = (
                Tarefa.objects.filter(status=Tarefa.Status.ABERTA).aggregate(m=Max("ordem"))["m"] or 0
            )
            tarefa.ordem = max_ordem + 1
            tarefa.save()

            messages.success(request, "Tarefa criada.")
            return go_back(request)
    else:
        form = TarefaForm()

    return render(request, "Gestao/tarefa_form.html", {"form": form, "modo": "Criar"})


# ============================================================
# EDITAR
# ============================================================
@login_required
def tarefa_editar(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_editar(request.user):
        return HttpResponseForbidden("Sem permissão para editar tarefas.")

    anexos = tarefa.anexos.all().order_by("-enviado_em")
    anexo_form = AnexoForm()

    if request.method == "POST":
        form = TarefaForm(request.POST, instance=tarefa)
        if form.is_valid():
            form.save()
            messages.success(request, "Tarefa atualizada.")
            return go_back(request)
    else:
        form = TarefaForm(instance=tarefa)

    return render(
        request,
        "Gestao/tarefa_form.html",
        {
            "form": form,
            "modo": "Editar",
            "tarefa": tarefa,
            "anexos": anexos,
            "anexo_form": anexo_form,
        },
    )


# ============================================================
# DELETAR
# ============================================================
@login_required
def tarefa_deletar(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_deletar(request.user):
        return HttpResponseForbidden("Apenas superuser pode deletar tarefas.")

    if request.method == "POST":
        tarefa.delete()
        messages.success(request, "Tarefa deletada.")
        return go_back(request)

    return render(request, "Gestao/tarefa_delete.html", {"tarefa": tarefa})


# ============================================================
# TOGGLE FEITA
# ============================================================
@login_required
@require_POST
def tarefa_toggle_status(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    if tarefa.status == Tarefa.Status.FEITA:
        tarefa.status = Tarefa.Status.ABERTA
        tarefa.finalizado_em = None
        tarefa.save(update_fields=["status", "finalizado_em", "atualizado_em"])
    else:
        tarefa.finalizar()
        tarefa.save(update_fields=["status", "finalizado_em", "atualizado_em"])

    return go_back(request)


# ============================================================
# TOGGLE EXECUTANDO
# ============================================================
@login_required
@require_POST
def tarefa_toggle_executando(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    if tarefa.status == Tarefa.Status.EXECUTANDO:
        tarefa.parar_execucao()
        tarefa.save(update_fields=["status", "atualizado_em"])
    else:
        # se tava feita, reabre e coloca executando
        if tarefa.status == Tarefa.Status.FEITA:
            tarefa.finalizado_em = None
        tarefa.iniciar_execucao()
        tarefa.save(update_fields=["status", "iniciado_em", "finalizado_em", "atualizado_em"])

    return go_back(request)


# ============================================================
# REORDENAR (drag)
# ============================================================
@login_required
@require_POST
def tarefa_reordenar(request):
    if not pode_editar(request.user):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        ids = payload.get("ids", [])

        for i, tid in enumerate(ids, start=1):
            Tarefa.objects.filter(id=tid, status=Tarefa.Status.ABERTA).update(ordem=i)

        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)


# ============================================================
# PRIORIDADE
# ============================================================
@login_required
@require_POST
def tarefa_toggle_prioridade(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_prioridade(request.user):
        return HttpResponseForbidden("Apenas superuser pode alterar prioridade.")

    tarefa.prioridade = not bool(tarefa.prioridade)
    tarefa.save(update_fields=["prioridade", "atualizado_em"])

    return go_back(request)


# ============================================================
# COMENTÁRIO
# ============================================================
@login_required
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
        messages.error(request, "Comentário inválido.")

    return go_back(request)


# ============================================================
# ANEXOS (LISTA)
# ============================================================
@login_required
def tarefa_anexos(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    anexos = tarefa.anexos.all().order_by("-enviado_em")
    return render(request, "Gestao/tarefa_anexos.html", {"tarefa": tarefa, "anexos": anexos})


# ============================================================
# ANEXO UPLOAD
# ============================================================
@login_required
@require_POST
def anexo_upload(request, pk):
    tarefa = get_object_or_404(Tarefa, pk=pk)

    if not pode_anexar(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão para anexar.")

    form = AnexoForm(request.POST, request.FILES)
    if form.is_valid():
        anexo = form.save(commit=False)
        anexo.tarefa = tarefa
        anexo.enviado_por = request.user
        anexo.save()
        messages.success(request, "Anexo enviado.")
    else:
        messages.error(request, "Falha ao enviar anexo.")

    return go_back(request)


# ============================================================
# ANEXO DOWNLOAD
# ============================================================
@login_required
def anexo_download(request, anexo_id):
    anexo = get_object_or_404(Anexo, pk=anexo_id)
    tarefa = anexo.tarefa

    if not pode_ver_tarefa(request.user, tarefa):
        return HttpResponseForbidden("Sem permissão.")

    if not anexo.arquivo:
        raise Http404("Arquivo não encontrado.")

    return FileResponse(anexo.arquivo.open("rb"), as_attachment=False, filename=anexo.nome_original or "anexo")