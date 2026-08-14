from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Tarefa

User = get_user_model()


class FiltroResponsavelTodosTests(TestCase):
    """
    Filtro "Responsável": sem selecionar nada mostra só os cards do próprio
    logado; selecionar "Todos" mostra o quadro inteiro; selecionar um
    usuário específico mostra só os cards desse usuário. Antes, "Todos"
    mandava value="" e ficava indistinguível de "nada selecionado".
    """

    def setUp(self):
        grupo_gestao, _ = Group.objects.get_or_create(name="GESTAO")
        grupo_gestor, _ = Group.objects.get_or_create(name="GESTAO_GESTOR")

        self.gestor = User.objects.create_user(username="gestor.teste", is_staff=True)
        self.gestor.groups.add(grupo_gestao)
        if hasattr(self.gestor, "perfil"):
            self.gestor.perfil.deve_trocar_senha = False
            self.gestor.perfil.save()

        # GESTAO_GESTOR: tem acesso ao quadro, mas não pode filtrar "todos"
        # (só GESTAO/superuser pode) — usado no teste de restrição abaixo.
        self.outro = User.objects.create_user(username="outro.teste")
        self.outro.groups.add(grupo_gestor)
        if hasattr(self.outro, "perfil"):
            self.outro.perfil.deve_trocar_senha = False
            self.outro.perfil.save()

        agora = timezone.now()
        self.tarefa_gestor = Tarefa.objects.create(
            titulo="Tarefa do gestor", criada_por=self.gestor, atribuida_para=self.gestor,
            status="aberta", prazo=agora,
        )
        self.tarefa_outro = Tarefa.objects.create(
            titulo="Tarefa do outro", criada_por=self.outro, atribuida_para=self.outro,
            status="aberta", prazo=agora,
        )

        self.client.force_login(self.gestor)

    def test_sem_filtro_mostra_so_do_logado(self):
        resp = self.client.get(reverse("gestao:quadro"))
        titulos = [t.titulo for t in resp.context["abertas"]]
        self.assertIn("Tarefa do gestor", titulos)
        self.assertNotIn("Tarefa do outro", titulos)

    def test_filtro_todos_mostra_tudo(self):
        resp = self.client.get(reverse("gestao:quadro"), {"user": "todos"})
        titulos = [t.titulo for t in resp.context["abertas"]]
        self.assertIn("Tarefa do gestor", titulos)
        self.assertIn("Tarefa do outro", titulos)

    def test_filtro_usuario_especifico_mostra_so_dele(self):
        resp = self.client.get(reverse("gestao:quadro"), {"user": str(self.outro.id)})
        titulos = [t.titulo for t in resp.context["abertas"]]
        self.assertIn("Tarefa do outro", titulos)
        self.assertNotIn("Tarefa do gestor", titulos)

    def test_nao_gestor_ignora_filtro_todos(self):
        """Quem não é gestor não pode ver tudo, mesmo forçando ?user=todos na URL."""
        self.client.force_login(self.outro)
        resp = self.client.get(reverse("gestao:quadro"), {"user": "todos"})
        titulos = [t.titulo for t in resp.context["abertas"]]
        self.assertIn("Tarefa do outro", titulos)
        self.assertNotIn("Tarefa do gestor", titulos)
