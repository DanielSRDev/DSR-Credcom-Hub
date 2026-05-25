from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages


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
            request.user.save()
            perfil.deve_trocar_senha = False
            perfil.save(update_fields=["deve_trocar_senha"])
            update_session_auth_hash(request, request.user)  # mantém logado
            messages.success(request, "Senha criada com sucesso! Bem-vindo(a).")
            return redirect("ambiente")

    return render(request, "registration/primeiro_acesso.html", {"erro": erro})
