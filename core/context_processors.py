def modulos_permitidos(request):
    user = getattr(request, "user", None)

    pode_gestao = False
    pode_operacao = False
    pode_nibo = False

    if user and user.is_authenticated:
        groups = set(user.groups.values_list("name", flat=True))

        # Gestão
        pode_gestao = bool(groups & {"GESTAO", "GESTAO_GESTOR", "GESTAO_GESTORA", "GESTAO_USUARIO"})

        # Operação
        pode_operacao = bool(groups & {"OPERACAO", "OPERACAO_SUPERVISOR", "OPERACAO_CORDENACAO"})

        # Nibo (ajusta se tiver mais grupos no futuro)
        pode_nibo = bool(groups & {"NIBO"})

    return {
        "pode_gestao": pode_gestao,
        "pode_operacao": pode_operacao,
        "pode_nibo": pode_nibo,
    }