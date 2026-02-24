#backoffice/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def ambiente(request):
    # flags vêm do context_processor
    return render(request, "ambiente.html")


