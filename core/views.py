from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from django.utils import timezone

from .models import AnotacaoPessoal, JornalPost, JornalLeitura, JornalLike


@login_required
def primeiro_acesso(request):
    """
    Exibida quando deve_trocar_senha = True.
    Força o usuário a definir uma nova senha antes de acessar qualquer módulo.
    Após salvar, deve_trocar_senha vira False e a sessão continua ativa.
    """
    try:
        perfil = request.user.perfil
    except Exception:
        # Perfil não existe → não bloqueia
        return redirect("ambiente")

    if not perfil.deve_trocar_senha:
        return redirect("ambiente")

    erro = None

    if request.method == "POST":
        nova = request.POST.get("nova_senha", "").strip()
        confirma = request.POST.get("confirmar_senha", "").strip()

        if not nova:
            erro = "A nova senha não pode estar em branco."
        elif len(nova) < 6:
            erro = "A senha deve ter pelo menos 6 caracteres."
        elif nova != confirma:
            erro = "As senhas não coincidem."

        if not erro:
            request.user.set_password(nova)
            request.user._skip_primeiro_acesso = True  # suprime signal pre_save
            request.user.save()
            perfil.deve_trocar_senha = False
            perfil.save(update_fields=["deve_trocar_senha"])
            update_session_auth_hash(request, request.user)  # mantém logado
            messages.success(request, "Senha criada com sucesso! Bem-vindo(a).")
            return redirect("ambiente")

    return render(request, "registration/primeiro_acesso.html", {"erro": erro})


# ── Anotações pessoais ────────────────────────────────────────────────────────

def _voltar(request):
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "ambiente"
    return redirect(next_url)


def _cor_do_post(request):
    cor = request.POST.get("cor") or AnotacaoPessoal.Cor.PADRAO
    if cor not in AnotacaoPessoal.Cor.values:
        cor = AnotacaoPessoal.Cor.PADRAO
    return cor


def _lembrete_do_post(request):
    lembrete_str = request.POST.get("lembrete_em", "").strip()
    if not lembrete_str:
        return None
    from django.utils.dateparse import parse_datetime
    from django.utils import timezone
    lembrete_em = parse_datetime(lembrete_str)
    if lembrete_em and timezone.is_naive(lembrete_em):
        lembrete_em = timezone.make_aware(lembrete_em)
    return lembrete_em


@login_required
@require_POST
def anotacao_criar(request):
    texto = request.POST.get("texto", "").strip()
    if texto:
        AnotacaoPessoal.objects.create(
            user=request.user,
            texto=texto,
            cor=_cor_do_post(request),
            lembrete_em=_lembrete_do_post(request),
        )
    return _voltar(request)


@login_required
@require_POST
def anotacao_editar(request, pk):
    nota = get_object_or_404(AnotacaoPessoal, pk=pk, user=request.user)
    texto = request.POST.get("texto", "").strip()
    if texto:
        nota.texto = texto
        nota.cor = _cor_do_post(request)
        nota.lembrete_em = _lembrete_do_post(request)
        nota.save(update_fields=["texto", "cor", "lembrete_em"])
    return _voltar(request)


@login_required
@require_POST
def anotacao_toggle(request, pk):
    nota = get_object_or_404(AnotacaoPessoal, pk=pk, user=request.user)
    nota.concluida = not nota.concluida
    nota.save(update_fields=["concluida"])
    return _voltar(request)


@login_required
@require_POST
def anotacao_fixar(request, pk):
    nota = get_object_or_404(AnotacaoPessoal, pk=pk, user=request.user)
    nota.fixada = not nota.fixada
    nota.save(update_fields=["fixada"])
    return _voltar(request)


@login_required
@require_POST
def anotacao_excluir(request, pk):
    nota = get_object_or_404(AnotacaoPessoal, pk=pk, user=request.user)
    nota.delete()
    return _voltar(request)


# ── Jornal (mural de novidades) ───────────────────────────────────────────────

IMAGEM_EXTS = ("jpg", "jpeg", "png", "gif", "webp", "bmp")


def _split_anexo(f):
    """
    Recebe um único arquivo enviado e retorna (imagem, arquivo) — preenchendo
    apenas o campo correspondente conforme a extensão do arquivo.
    """
    if not f:
        return None, None
    ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
    if ext in IMAGEM_EXTS:
        return f, None
    return None, f


@login_required
@require_POST
def jornal_criar(request):
    if not getattr(getattr(request.user, "perfil", None), "pode_publicar_jornal", False):
        messages.error(request, "Você não tem permissão para publicar no Jornal.")
        return _voltar(request)

    titulo = request.POST.get("titulo", "").strip()
    conteudo = request.POST.get("conteudo", "").strip()
    imagem, arquivo = _split_anexo(request.FILES.get("anexo"))

    if not titulo or not conteudo:
        messages.error(request, "Preencha o título e o conteúdo da publicação.")
        return _voltar(request)

    JornalPost.objects.create(
        titulo=titulo,
        conteudo=conteudo,
        imagem=imagem,
        arquivo=arquivo,
        autor=request.user,
    )
    messages.success(request, "Publicado no Jornal!")
    return _voltar(request)


@login_required
@require_POST
def jornal_editar(request, pk):
    post = get_object_or_404(JornalPost, pk=pk)

    if post.autor_id != request.user.id and not request.user.is_staff:
        messages.error(request, "Você não pode editar esta publicação.")
        return _voltar(request)

    titulo = request.POST.get("titulo", "").strip()
    conteudo = request.POST.get("conteudo", "").strip()

    if not titulo or not conteudo:
        messages.error(request, "Preencha o título e o conteúdo da publicação.")
        return _voltar(request)

    post.titulo = titulo
    post.conteudo = conteudo

    nova_imagem, novo_arquivo = _split_anexo(request.FILES.get("anexo"))

    if nova_imagem:
        post.imagem = nova_imagem
    elif request.POST.get("remover_imagem") == "on":
        post.imagem = None

    if novo_arquivo:
        post.arquivo = novo_arquivo
    elif request.POST.get("remover_arquivo") == "on":
        post.arquivo = None

    post.editado_em = timezone.now()
    post.save()

    messages.success(request, "Publicação atualizada.")
    return _voltar(request)


@login_required
@require_POST
def jornal_curtir(request, pk):
    post = get_object_or_404(JornalPost, pk=pk)

    like, criado = JornalLike.objects.get_or_create(post=post, user=request.user)
    if not criado:
        like.delete()
        liked = False
    else:
        liked = True

    total = post.likes.count()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "liked": liked, "total": total})

    return _voltar(request)


@login_required
@require_POST
def jornal_marcar_lido(request):
    ultimo = JornalPost.objects.first()
    leitura, _ = JornalLeitura.objects.get_or_create(user=request.user)
    leitura.ultimo_post_visto = ultimo
    leitura.save(update_fields=["ultimo_post_visto"])
    return JsonResponse({"ok": True})
