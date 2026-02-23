from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from core.permissions import tem_acesso

@login_required
def ambiente(request):
    return render(request, "ambiente.html", {
        "pode_gestao": tem_acesso(request.user, "GESTAO"),
        "pode_nibo": tem_acesso(request.user, "NIBO"),
    })
