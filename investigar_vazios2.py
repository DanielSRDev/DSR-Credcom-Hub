import sys, os
sys.path.insert(0, "C:/Desenvolvimento/Nibo/backoffice")
os.environ["DJANGO_SETTINGS_MODULE"] = "backoffice.settings"
import django; django.setup()

from painel_operacao.models import PainelOperacaoRelatorioGeral, PainelOperacaoRegistro
from django.db import connections

# Pega os aco_ids dos registros problema
registros = PainelOperacaoRelatorioGeral.objects.filter(
    numero_acordo__in=["24977","24974","24963","24943","24935","24926","24923","24915",
    "24898","24881","24878","24873","24863","24826","24803","24802","24782","24781",
    "24751","24756","24745","24736","24733","24732","24731","24726","24711",
    "24703","24702","24701","24690","24697","24693"]
)

aco_ids = list(registros.values_list("aco_id", flat=True))
print(f"aco_ids dos registros problemáticos: {aco_ids[:5]} ... (total: {len(aco_ids)})")

# Verifica se esses aco_ids existem em PainelOperacaoRegistro (outra tabela)
cross = PainelOperacaoRegistro.objects.filter(aco_id__in=aco_ids)
print(f"\nRegistros cruzados em PainelOperacaoRegistro: {cross.count()}")
for r in cross[:3]:
    print(f"  aco_id: {r.aco_id} | cliente: '{r.cliente}' | cpf: '{r.cpf_cnpj}' | credor: '{r.credor}' (cre_id: {r.cre_id})")

# Tenta consultar o banco stage diretamente para ver o que existe nesses acordos
print("\n=== CONSULTANDO BANCO STAGE DIRETAMENTE ===")
try:
    with connections["stage"].cursor() as cursor:
        placeholders = ",".join([str(i) for i in aco_ids[:5]])
        # Verifica se o acordo existe no stage
        cursor.execute(f"""
            SELECT a.aco_id, a.aco_numero, a.aco_status
            FROM dbo.tb_acordo a
            WHERE a.aco_id IN ({placeholders})
        """)
        rows = cursor.fetchall()
        print(f"  Acordos encontrados no tb_acordo: {len(rows)}")
        for row in rows:
            print(f"    aco_id={row[0]}, numero={row[1]}, status={row[2]}")

        # Verifica parcelas
        cursor.execute(f"""
            SELECT ap.aco_id, COUNT(*) as qtd_parcelas
            FROM dbo.tb_acordo_parcela ap
            WHERE ap.aco_id IN ({placeholders})
            GROUP BY ap.aco_id
        """)
        parcelas = cursor.fetchall()
        print(f"\n  Parcelas encontradas (tb_acordo_parcela): {len(parcelas)} acordos com parcelas")
        for row in parcelas:
            print(f"    aco_id={row[0]}: {row[1]} parcelas")

        # Verifica negociacao_vinculo
        cursor.execute(f"""
            SELECT nv.aco_id, COUNT(*) as qtd
            FROM dbo.tb_negociacao_vinculo nv
            WHERE nv.aco_id IN ({placeholders})
            GROUP BY nv.aco_id
        """)
        vinculos = cursor.fetchall()
        print(f"\n  Vínculos encontrados (tb_negociacao_vinculo): {len(vinculos)} acordos com vínculo")

        # Verifica tb_cliente_evento — o evc_id = aco_id?
        cursor.execute(f"""
            SELECT ce.evc_id, ce.cli_id, e.eve_nome
            FROM dbo.tb_cliente_evento ce
            INNER JOIN dbo.tb_evento e ON e.eve_id = ce.eve_id
            WHERE ce.evc_id IN ({placeholders})
              AND e.eve_nome = 'Acordo'
        """)
        eventos = cursor.fetchall()
        print(f"\n  Eventos 'Acordo' encontrados (tb_cliente_evento): {len(eventos)}")
        for row in eventos[:5]:
            print(f"    evc_id={row[0]}, cli_id={row[1]}, evento={row[2]}")

        # Tenta buscar o cliente a partir do cli_id do evento
        if eventos:
            cli_ids = [str(row[1]) for row in eventos if row[1]]
            if cli_ids:
                cli_ph = ",".join(cli_ids)
                cursor.execute(f"""
                    SELECT cl.cli_id, ps.pes_nome, ps.pes_cpfcnpj
                    FROM dbo.tb_cliente cl
                    LEFT JOIN dbo.tb_pessoa ps ON ps.pes_id = cl.cli_id
                    WHERE cl.cli_id IN ({cli_ph})
                """)
                clientes = cursor.fetchall()
                print(f"\n  Clientes encontrados via cli_id do evento: {len(clientes)}")
                for row in clientes[:5]:
                    print(f"    cli_id={row[0]}, nome='{row[1]}', cpf='{row[2]}'")

                # Tenta achar contrato/credor a partir do cliente
                cursor.execute(f"""
                    SELECT c.cli_id, con.con_id, con.con_numero, con.cre_id, cr.cre_sigla
                    FROM dbo.tb_cliente c
                    INNER JOIN dbo.tb_contrato con ON con.cli_id = c.cli_id
                    LEFT JOIN dbo.tb_credor cr ON cr.cre_id = con.cre_id
                    WHERE c.cli_id IN ({cli_ph})
                    ORDER BY con.con_id DESC
                """)
                contratos = cursor.fetchall()
                print(f"\n  Contratos encontrados via cli_id: {len(contratos)}")
                for row in contratos[:5]:
                    print(f"    cli_id={row[0]}, con_id={row[1]}, numero={row[2]}, cre_id={row[3]}, credor={row[4]}")

except Exception as e:
    print(f"  Erro ao consultar stage: {e}")
    print("  (Tentando com conexão 'default'...)")
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            print(f"  Conexão default OK")
    except Exception as e2:
        print(f"  Erro: {e2}")
