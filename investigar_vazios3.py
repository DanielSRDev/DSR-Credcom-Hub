import sys, os
sys.path.insert(0, "C:/Desenvolvimento/Nibo/backoffice")
os.environ["DJANGO_SETTINGS_MODULE"] = "backoffice.settings"
import django; django.setup()

from painel_operacao.models import PainelOperacaoRelatorioGeral
from django.db import connections

# 5 aco_ids problemáticos para diagnóstico
registros = PainelOperacaoRelatorioGeral.objects.filter(
    numero_acordo__in=["24977","24974","24963","24943","24935","24926","24923","24915",
    "24898","24881","24878","24873","24863","24826","24803","24802","24782","24781",
    "24751","24756","24745","24736","24733","24732","24731","24726","24711",
    "24703","24702","24701","24690","24697","24693"]
).values_list("aco_id", "numero_acordo")

aco_ids = [r[0] for r in registros]
numeros = [r[1] for r in registros]
sample_ids = aco_ids[:6]
placeholders = ",".join([str(i) for i in sample_ids])

print(f"Investigando {len(aco_ids)} acordos | amostra aco_ids: {sample_ids}")

with connections["cliente_db"].cursor() as cursor:

    # 1. Existe no tb_acordo?
    cursor.execute(f"SELECT aco_id, aco_numero, aco_status FROM dbo.tb_acordo WHERE aco_id IN ({placeholders})")
    rows = cursor.fetchall()
    print(f"\n[1] tb_acordo: {len(rows)} de {len(sample_ids)} encontrados")
    for r in rows:
        print(f"    aco_id={r[0]} | numero={r[1]} | status={r[2]}")

    # 2. Tem parcelas?
    cursor.execute(f"SELECT aco_id, COUNT(*) FROM dbo.tb_acordo_parcela WHERE aco_id IN ({placeholders}) GROUP BY aco_id")
    rows = cursor.fetchall()
    print(f"\n[2] tb_acordo_parcela: {len(rows)} acordos com parcelas")
    for r in rows:
        print(f"    aco_id={r[0]}: {r[1]} parcelas")

    # 3. Tem negociacao_vinculo?
    cursor.execute(f"SELECT aco_id, COUNT(*) FROM dbo.tb_negociacao_vinculo WHERE aco_id IN ({placeholders}) GROUP BY aco_id")
    rows = cursor.fetchall()
    print(f"\n[3] tb_negociacao_vinculo: {len(rows)} acordos com vínculo")

    # 4. Evento 'Acordo' para esses evc_id
    cursor.execute(f"""
        SELECT ce.evc_id, ce.cli_id, e.eve_nome, ce.evc_data
        FROM dbo.tb_cliente_evento ce
        INNER JOIN dbo.tb_evento e ON e.eve_id = ce.eve_id
        WHERE ce.evc_id IN ({placeholders}) AND e.eve_nome = 'Acordo'
    """)
    eventos = cursor.fetchall()
    print(f"\n[4] tb_cliente_evento (eve='Acordo'): {len(eventos)} encontrados")
    for r in eventos:
        print(f"    evc_id={r[0]} | cli_id={r[1]} | data={r[3]}")

    # 5. Tenta pegar dados do cliente via cli_id do evento
    if eventos:
        cli_ids = list(set([str(r[1]) for r in eventos if r[1]]))
        cli_ph = ",".join(cli_ids)
        cursor.execute(f"""
            SELECT cl.cli_id, ps.pes_nome, ps.pes_cpfcnpj
            FROM dbo.tb_cliente cl
            LEFT JOIN dbo.tb_pessoa ps ON ps.pes_id = cl.cli_id
            WHERE cl.cli_id IN ({cli_ph})
        """)
        clientes = cursor.fetchall()
        print(f"\n[5] Clientes via cli_id: {len(clientes)}")
        for r in clientes:
            print(f"    cli_id={r[0]} | nome='{r[1]}' | cpf='{r[2]}'")

        # 6. Contratos do cliente — por onde vem o credor?
        cursor.execute(f"""
            SELECT con.cli_id, con.con_id, con.con_numero, con.cre_id, cr.cre_sigla
            FROM dbo.tb_contrato con
            LEFT JOIN dbo.tb_credor cr ON cr.cre_id = con.cre_id
            WHERE con.cli_id IN ({cli_ph})
            ORDER BY con.con_id DESC
        """)
        contratos = cursor.fetchall()
        print(f"\n[6] Contratos via cli_id: {len(contratos)}")
        for r in contratos[:10]:
            print(f"    cli_id={r[0]} | con_id={r[1]} | numero={r[2]} | cre_id={r[3]} | credor={r[4]}")

    # 7. Verifica se o JOIN proposto (evento.cli_id -> contrato) resolveria
    print("\n[7] Tentando rota alternativa: evento.cli_id -> tb_contrato mais recente")
    if eventos:
        for evc_id, cli_id, _, data in eventos[:3]:
            cursor.execute(f"""
                SELECT TOP 1
                    ps.pes_nome, ps.pes_cpfcnpj,
                    con.con_numero, con.cre_id, cr.cre_sigla
                FROM dbo.tb_cliente cl
                LEFT JOIN dbo.tb_pessoa ps ON ps.pes_id = cl.cli_id
                LEFT JOIN dbo.tb_contrato con ON con.cli_id = cl.cli_id
                LEFT JOIN dbo.tb_credor cr ON cr.cre_id = con.cre_id
                WHERE cl.cli_id = {cli_id}
                ORDER BY con.con_id DESC
            """)
            row = cursor.fetchone()
            if row:
                print(f"    evc_id={evc_id}: nome='{row[0]}' cpf='{row[1]}' contrato={row[2]} cre_id={row[3]} credor={row[4]}")
            else:
                print(f"    evc_id={evc_id}: sem resultado")
