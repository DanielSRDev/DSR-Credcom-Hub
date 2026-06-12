from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def financeiro(request):
    return render(request, "financeiro/financeiro.html")
