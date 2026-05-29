import sys, os
sys.path.insert(0, "C:/Desenvolvimento/Nibo/backoffice")
os.environ["DJANGO_SETTINGS_MODULE"] = "backoffice.settings"
import django; django.setup()

from painel_operacao.models import PainelOperacaoRelatorioGeral

acordos = [
    "24977","24974","24963","24943","24935","24926","24923","24915","24898",
    "24881","24878","24873","24863","24826","24803","24802","24782","24781",
    "24751","24756","24745","24736","24733","24732","24731","24726","24711",
    "24703","24702","24701","24690","24697","24693",
]

qs = PainelOperacaoRelatorioGeral.objects.filter(numero_acordo__in=acordos).order_by("numero_acordo")

print(f"Total encontrado: {qs.count()} de {len(acordos)} buscados\n")

campos = ["numero_acordo", "aco_id", "cliente", "cpf_cnpj", "credor", "cre_id",
          "emitido_por_nome", "emitido_por_login", "supervisor_nome",
          "status_acordo", "origem_registro", "data_emissao",
          "valor_emissao", "valor_pago", "valor_avencer", "valor_quebra"]

# Verifica padrão de vazios por campo
from collections import Counter
vazios_por_campo = {c: 0 for c in campos}

for r in qs:
    for c in campos:
        val = getattr(r, c, None)
        if val is None or str(val).strip() == "" or str(val).strip() == "0" or str(val) == "0.00":
            vazios_por_campo[c] += 1

print("=== CAMPOS COM VALORES VAZIOS/ZERO ===")
for campo, qtd in vazios_por_campo.items():
    if qtd > 0:
        print(f"  {campo}: {qtd} registros vazios")

print("\n=== AMOSTRA DOS PRIMEIROS 5 REGISTROS ===")
for r in qs[:5]:
    print(f"\n  Acordo: {r.numero_acordo} | aco_id: {r.aco_id} | origem: {r.origem_registro}")
    print(f"  Cliente: '{r.cliente}' | CPF: '{r.cpf_cnpj}'")
    print(f"  Credor: '{r.credor}' (cre_id: {r.cre_id})")
    print(f"  Operador: '{r.emitido_por_nome}' ({r.emitido_por_login})")
    print(f"  Supervisor: '{r.supervisor_nome}'")
    print(f"  Status: '{r.status_acordo}' | Emissão: {r.data_emissao}")
    print(f"  Emissão: {r.valor_emissao} | Pago: {r.valor_pago} | A Vencer: {r.valor_avencer} | Quebra: {r.valor_quebra}")

# Checa se existem no banco com aco_id mas sem numero_acordo
print("\n=== VERIFICANDO SE ACORDOS EXISTEM POR ACO_ID ===")
# Tenta buscar por aco_id também
for num in acordos[:10]:
    try:
        aco_id_num = int(num)
        por_aco = PainelOperacaoRelatorioGeral.objects.filter(aco_id=aco_id_num)
        por_num = PainelOperacaoRelatorioGeral.objects.filter(numero_acordo=num)
        if por_aco.exists() or por_num.exists():
            r = (por_num.first() or por_aco.first())
            print(f"  {num}: encontrado | cliente='{r.cliente}' cpf='{r.cpf_cnpj}' credor='{r.credor}' origem={r.origem_registro}")
        else:
            print(f"  {num}: NAO encontrado no banco")
    except Exception as e:
        print(f"  {num}: erro - {e}")

# Origem dos registros
print("\n=== DISTRIBUIÇÃO POR ORIGEM ===")
from django.db.models import Count
origens = qs.values("origem_registro").annotate(qtd=Count("id"))
for o in origens:
    print(f"  {o['origem_registro']}: {o['qtd']} registros")
