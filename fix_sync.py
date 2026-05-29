import sys, os
sys.path.insert(0, 'C:/Desenvolvimento/Nibo/backoffice')
os.environ["DJANGO_SETTINGS_MODULE"] = "backoffice.settings"
import django; django.setup()

from painel_operacao.models import PainelOperacaoRegistro, PainelOperacaoRelatorioGeral
from painel_operacao.services import sincronizar_painel_operacao, sincronizar_relatorio_geral
from datetime import date

acordos_problema = {
    "24977","24974","24963","24943","24935","24926","24923","24915","24898",
    "24881","24878","24873","24863","24826","24803","24802","24782","24781",
    "24751","24756","24745","24736","24733","24732","24731","24726","24711",
    "24703","24702","24701","24690","24697","24693",
}

# 1. Estado atual do PainelOperacaoRegistro
print("=== ESTADO ATUAL - PainelOperacaoRegistro ===")
reg = PainelOperacaoRegistro.objects.filter(numero_acordo__in=acordos_problema)
print(f"Encontrados: {reg.count()} de {len(acordos_problema)}")
vazios = sum(1 for r in reg if not r.cliente and not r.credor)
print(f"Com dados vazios: {vazios}")

# 2. Re-sync do painel operacao
print("\n=== SYNC 1: sincronizar_painel_operacao (maio/2026) ===")
r1 = sincronizar_painel_operacao(date(2026, 5, 1), date(2026, 5, 31))
print(f"Resultado: {r1['mensagem']}")

# 3. Verifica PainelOperacaoRegistro após sync
print("\n=== APÓS SYNC PAINEL - PainelOperacaoRegistro ===")
reg = PainelOperacaoRegistro.objects.filter(numero_acordo__in=acordos_problema)
print(f"Encontrados: {reg.count()} de {len(acordos_problema)}")
vazios_depois = 0
for r in reg:
    if not r.cliente and not r.credor:
        vazios_depois += 1
        print(f"  [{r.numero_acordo}] AINDA VAZIO")
    else:
        nome = (r.cliente or "")[:25]
        print(f"  [{r.numero_acordo}] OK: {nome} | {r.credor}")
print(f"Vazios restantes: {vazios_depois}")

# 4. Re-sync do relatorio geral
print("\n=== SYNC 2: sincronizar_relatorio_geral (maio/2026) ===")
r2 = sincronizar_relatorio_geral(date(2026, 5, 1), date(2026, 5, 31))
print(f"Resultado: {r2['mensagem']}")

# 5. Verifica resultado final
print("\n=== RESULTADO FINAL - PainelOperacaoRelatorioGeral ===")
rg = PainelOperacaoRelatorioGeral.objects.filter(numero_acordo__in=acordos_problema)
print(f"Encontrados: {rg.count()} de {len(acordos_problema)}")
vazios_final = 0
for r in rg:
    if not r.cliente and not r.credor:
        vazios_final += 1
        print(f"  [{r.numero_acordo}] AINDA VAZIO")
    else:
        nome = (r.cliente or "")[:25]
        print(f"  [{r.numero_acordo}] OK: {nome} | {r.credor} (cre_id={r.cre_id})")
print(f"\nFINAL: {rg.count() - vazios_final} corrigidos, {vazios_final} ainda com campos vazios")
