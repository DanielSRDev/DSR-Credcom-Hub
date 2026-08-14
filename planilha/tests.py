from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from operacao.models import Equipe

from .models import PlanilhaCompartilhamento, PlanilhaContrato, PlanilhaImportacao
from . import services, visao


class VisaoSupervisorEquipeTests(TestCase):
    """Supervisor (GESTAO_GESTOR) vê os contratos dos MEMBROS da equipe onde
    ele está cadastrado como Supervisor (operacao.Equipe) — não depende de
    carteira/cre_id."""

    def setUp(self):
        User = get_user_model()
        grupo_gestor, _ = Group.objects.get_or_create(name="GESTAO_GESTOR")

        self.supervisor = User.objects.create_user(
            username="supervisor.teste", first_name="Supervisor", last_name="Teste",
        )
        self.supervisor.groups.add(grupo_gestor)

        self.membro = User.objects.create_user(
            username="operador.teste", first_name="Operador", last_name="Teste",
        )
        self.fora_da_equipe = User.objects.create_user(
            username="outro.operador", first_name="Outro", last_name="Operador",
        )

        equipe = Equipe.objects.create(nome="Equipe Teste", ativa=True)
        equipe.supervisores.add(self.supervisor)
        equipe.membros.add(self.membro)

        importacao = PlanilhaImportacao.objects.create(cre_id=999999998, carteira_nome="Carteira Teste")
        self.contrato_do_membro = PlanilhaContrato.objects.create(
            importacao=importacao, cre_id=999999998, carteira_nome="Carteira Teste",
            operador_nome="Operador Teste", nr_contrato="TESTE-1", nome_cliente="Cliente Teste",
        )
        self.contrato_de_fora = PlanilhaContrato.objects.create(
            importacao=importacao, cre_id=999999998, carteira_nome="Carteira Teste",
            operador_nome="Outro Operador", nr_contrato="TESTE-2", nome_cliente="Cliente Teste 2",
        )

    def test_supervisor_ve_contrato_do_membro_da_equipe(self):
        ids = set(visao.contratos_visiveis(self.supervisor).values_list("pk", flat=True))
        self.assertIn(self.contrato_do_membro.pk, ids)

    def test_supervisor_nao_ve_contrato_de_fora_da_equipe(self):
        ids = set(visao.contratos_visiveis(self.supervisor).values_list("pk", flat=True))
        self.assertNotIn(self.contrato_de_fora.pk, ids)

    def test_supervisor_sem_equipe_nao_ve_nada(self):
        User = get_user_model()
        sem_equipe = User.objects.create_user(username="supervisor.sem.equipe")
        sem_equipe.groups.add(Group.objects.get(name="GESTAO_GESTOR"))
        self.assertFalse(visao.contratos_visiveis(sem_equipe).exists())


class FiltroCorTests(TestCase):
    def setUp(self):
        importacao = PlanilhaImportacao.objects.create(cre_id=999999997, carteira_nome="Carteira Teste Cor")
        self.com_cor = PlanilhaContrato.objects.create(
            importacao=importacao, cre_id=999999997, carteira_nome="Carteira Teste Cor",
            operador_nome="Fulano", nr_contrato="COR-1", nome_cliente="Cliente A",
            destaque_cor="#ffd43b",
        )
        self.sem_cor = PlanilhaContrato.objects.create(
            importacao=importacao, cre_id=999999997, carteira_nome="Carteira Teste Cor",
            operador_nome="Fulano", nr_contrato="COR-2", nome_cliente="Cliente B",
        )

    def test_filtra_por_cor_especifica(self):
        qs = visao.aplicar_filtros(PlanilhaContrato.objects.all(), QueryDict("cor=%23ffd43b"))
        ids = set(qs.values_list("pk", flat=True))
        self.assertIn(self.com_cor.pk, ids)
        self.assertNotIn(self.sem_cor.pk, ids)

    def test_filtra_sem_cor(self):
        qs = visao.aplicar_filtros(PlanilhaContrato.objects.all(), QueryDict("cor=__sem__"))
        ids = set(qs.values_list("pk", flat=True))
        self.assertIn(self.sem_cor.pk, ids)
        self.assertNotIn(self.com_cor.pk, ids)


class CompartilhamentoTests(TestCase):
    """PlanilhaCompartilhamento libera a base de um colega pra outro usuário."""

    def setUp(self):
        User = get_user_model()
        self.operador_a = User.objects.create_user(
            username="op.a.teste", first_name="Operador", last_name="A",
        )
        self.operador_b = User.objects.create_user(
            username="op.b.teste", first_name="Operador", last_name="B",
        )

        importacao = PlanilhaImportacao.objects.create(cre_id=999999996, carteira_nome="Carteira Compartilhada")
        self.contrato_b = PlanilhaContrato.objects.create(
            importacao=importacao, cre_id=999999996, carteira_nome="Carteira Compartilhada",
            operador_nome="Operador B", nr_contrato="COMP-1", nome_cliente="Cliente Compartilhado",
        )

    def test_sem_compartilhamento_a_nao_ve_base_de_b(self):
        ids = set(visao.contratos_visiveis(self.operador_a).values_list("pk", flat=True))
        self.assertNotIn(self.contrato_b.pk, ids)

    def test_com_compartilhamento_a_passa_a_ver_base_de_b(self):
        comp = PlanilhaCompartilhamento.objects.create(usuario=self.operador_a, ativo=True)
        comp.colegas.add(self.operador_b)

        ids = set(visao.contratos_visiveis(self.operador_a).values_list("pk", flat=True))
        self.assertIn(self.contrato_b.pk, ids)

    def test_compartilhamento_inativo_nao_libera_acesso(self):
        comp = PlanilhaCompartilhamento.objects.create(usuario=self.operador_a, ativo=False)
        comp.colegas.add(self.operador_b)

        ids = set(visao.contratos_visiveis(self.operador_a).values_list("pk", flat=True))
        self.assertNotIn(self.contrato_b.pk, ids)


class ImportarModoAdicionarTests(TestCase):
    """modo='adicionar' insere só os Nr Contrato novos, sem tocar na base atual."""

    CRE_FAKE = 999999993

    def _linha(self, i, vlr=100):
        return {
            "cre_id": self.CRE_FAKE, "carteira": "Carteira Teste", "operador": "Fulano",
            "nr_contrato": f"C-{i}", "tipo_contrato": "", "empreendimento": "",
            "atraso": 0, "vlr_total": vlr, "status_antigo": "",
            "cpf_cnpj": "", "cpf_digitos": "", "nome": f"Cliente {i}",
            "cod_empresa": "", "cod_obra": "",
        }

    def setUp(self):
        PlanilhaImportacao.objects.filter(cre_id=self.CRE_FAKE).delete()
        services.importar(
            [self._linha(i) for i in range(1, 4)],
            user=None, importado_mesmo_com_erros=False, arquivo_nome="base1.xlsx",
        )
        self.c1 = PlanilhaContrato.objects.get(cre_id=self.CRE_FAKE, nr_contrato="C-1")
        self.c1.prioridade = True
        self.c1.destaque_cor = "#ffd43b"
        self.c1.save()

    def tearDown(self):
        PlanilhaImportacao.objects.filter(cre_id=self.CRE_FAKE).delete()

    def test_diff_na_validacao_mostra_novos_e_existentes(self):
        linhas_novas = [self._linha(i, vlr=999) for i in range(1, 7)]
        analise = services.validar(linhas_novas)
        sub = next(s for s in analise["substituicoes"] if s["cre_id"] == self.CRE_FAKE)
        self.assertEqual(sub["contratos_novos"], 3)
        self.assertEqual(sub["contratos_ja_existentes"], 3)

    def test_adicionar_nao_toca_contratos_existentes(self):
        linhas_novas = [self._linha(i, vlr=999) for i in range(1, 7)]
        services.importar(
            linhas_novas, user=None, importado_mesmo_com_erros=False,
            arquivo_nome="base2.xlsx", modo="adicionar",
        )
        self.c1.refresh_from_db()
        self.assertTrue(self.c1.prioridade)
        self.assertEqual(self.c1.destaque_cor, "#ffd43b")
        self.assertEqual(self.c1.vlr_total, 100)  # não foi sobrescrito pelo 999 do arquivo novo

    def test_adicionar_insere_so_os_contratos_novos(self):
        linhas_novas = [self._linha(i, vlr=999) for i in range(1, 7)]
        resultado = services.importar(
            linhas_novas, user=None, importado_mesmo_com_erros=False,
            arquivo_nome="base2.xlsx", modo="adicionar",
        )[0]
        self.assertEqual(resultado["inseridos"], 3)
        self.assertEqual(resultado["ignorados_ja_existentes"], 3)
        self.assertTrue(resultado["adicionou"])
        self.assertFalse(resultado["substituiu"])

        total = PlanilhaContrato.objects.filter(cre_id=self.CRE_FAKE).count()
        self.assertEqual(total, 6)
        c4 = PlanilhaContrato.objects.get(cre_id=self.CRE_FAKE, nr_contrato="C-4")
        self.assertEqual(c4.vlr_total, 999)


class OrdenacaoEBuscaGlobalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="super.teste", email="super@teste.com", password="x",
        )
        self.superuser.perfil.deve_trocar_senha = False
        self.superuser.perfil.save(update_fields=["deve_trocar_senha"])
        self.client.force_login(self.superuser)

        importacao = PlanilhaImportacao.objects.create(cre_id=999999995, carteira_nome="Carteira Ordenacao")
        PlanilhaContrato.objects.create(
            importacao=importacao, cre_id=999999995, carteira_nome="Carteira Ordenacao",
            operador_nome="Zeca", nr_contrato="ORD-1", nome_cliente="Zulmira",
            cpf_cnpj="11111111111",
        )
        PlanilhaContrato.objects.create(
            importacao=importacao, cre_id=999999995, carteira_nome="Carteira Ordenacao",
            operador_nome="Ana", nr_contrato="ORD-2", nome_cliente="Ana Beatriz",
            cpf_cnpj="22222222222",
        )

    def test_ordena_por_nome_asc(self):
        resp = self.client.get(reverse("planilha:index"), {"sort": "nome_cliente", "dir": "asc"})
        nomes = [c.nome_cliente for c in resp.context["page"].object_list]
        self.assertEqual(nomes, sorted(nomes))

    def test_busca_global_encontra_fora_da_propria_base(self):
        resp = self.client.get(reverse("planilha:busca_global"), {"q": "Zulmira"})
        resultados = resp.context["resultados"]
        self.assertEqual(len(resultados), 1)
        r = resultados[0]
        self.assertEqual(r["operador_nome"], "Zeca")
        self.assertEqual(set(r.keys()), {"nr_contrato", "nome_cliente", "cpf_cnpj", "carteira_nome", "operador_nome"})


class ExportarFiltradosTests(TestCase):
    """'Exportar tudo filtrado' deve trazer TODOS os contratos do filtro,
    não só os 50 de uma página."""

    CRE_FAKE = 999999991

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="export.filtro.teste", email="x@x.com", password="x",
        )
        self.user.perfil.deve_trocar_senha = False
        self.user.perfil.save(update_fields=["deve_trocar_senha"])
        self.client.force_login(self.user)

        importacao = PlanilhaImportacao.objects.create(
            cre_id=self.CRE_FAKE, carteira_nome="Carteira Export Filtro", total_contratos=70,
        )
        PlanilhaContrato.objects.bulk_create([
            PlanilhaContrato(
                importacao=importacao, cre_id=self.CRE_FAKE, carteira_nome="Carteira Export Filtro",
                operador_nome="Fulano", nr_contrato=f"EXP-{i}", nome_cliente=f"Cliente {i}",
            )
            for i in range(70)
        ])

    def tearDown(self):
        PlanilhaImportacao.objects.filter(cre_id=self.CRE_FAKE).delete()

    def test_exporta_todos_nao_so_a_pagina(self):
        import pandas as pd
        from io import BytesIO

        resp = self.client.get(reverse("planilha:exportar_filtrados"), {"carteira": str(self.CRE_FAKE)})
        self.assertEqual(resp.status_code, 200)
        df = pd.read_excel(BytesIO(resp.content))
        self.assertEqual(len(df), 70)
