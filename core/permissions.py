def tem_acesso(user, grupo):
    if not user.is_authenticated:
        return False
    return user.groups.filter(name=grupo).exists()
