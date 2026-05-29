import sys, os
sys.path.insert(0, 'C:/Desenvolvimento/Nibo/backoffice')
os.environ["DJANGO_SETTINGS_MODULE"] = "backoffice.settings"
import django; django.setup()

from django.db import connections
from painel_operacao.queries import SQL_RELATORIO_GERAL_HUB_BASE

# Testa a query diretamente para os acordos problemáticos
# Período de maio/2026
data_ini = "2026-05-01"
data_fim = "2026-05-31"

with connections["cliente_db"].cursor() as cursor:
    print("Executando SQL_RELATORIO_GERAL_HUB_BASE para maio/2026...")
    cursor.execute(SQL_RELATORIO_GERAL_HUB_BASE, [data_ini, data_fim])
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    print(f"Total de linhas retornadas: {len(rows)}")

    # Filtra pelos números problemáticos
    acordos_problema = {
        "24977","24974","24963","24943","24935","24926","24923","24915","24898",
        "24881","24878","24873","24863","24826","24803","24802","24782","24781",
        "24751","24756","24745","24736","24733","24732","24731","24726","24711",
        "24703","24702","24701","24690","24697","24693",
    }

    idx_numero = cols.index("numero_acordo")
    idx_cliente = cols.index("cliente")
    idx_cpf = cols.index("cpf_cnpj")
    idx_credor = cols.index("credor")
    idx_cre_id = cols.index("cre_id")

    print("\nAcordos problemáticos encontrados na query:")
    encontrados = 0
    vazios = 0
    for row in rows:
        if str(row[idx_numero]) in acordos_problema:
            encontrados += 1
            cliente = row[idx_cliente]
            cpf = row[idx_cpf]
            credor = row[idx_credor]
            cre_id = row[idx_cre_id]
            status = "VAZIO" if not cliente and not credor else "OK"
            if status == "VAZIO":
                vazios += 1
            print(f"  [{row[idx_numero]}] {status} | cliente={repr(cliente)} | credor={repr(credor)} | cre_id={cre_id}")

    print(f"\nTotal: {encontrados} encontrados na query, {vazios} ainda vazios")
    if encontrados == 0:
        print("\nATENÇÃO: Acordos problemáticos não estão na query! Verificando se estão na tabela...")
        # Pega os 5 primeiros da query para validar
        print("\nPrimeiros 5 registros da query:")
        for row in rows[:5]:
            print(f"  numero_acordo={row[idx_numero]} | cliente={repr(row[idx_cliente])} | credor={repr(row[idx_credor])}")
