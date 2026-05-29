import sys, os
sys.path.insert(0, 'C:/Desenvolvimento/Nibo/backoffice')
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
print(f"Total encontrado: {qs.count()} de {len(acordos)}")

vazios = 0
for r in qs:
    campos_vazios = []
    for campo in ["cliente", "cpf_cnpj", "credor", "cre_id"]:
        val = getattr(r, campo, None)
        if not val or str(val).strip() in ("", "0", "None"):
            campos_vazios.append(campo)
    nome_curto = (r.cliente or "")[:30]
    if campos_vazios:
        vazios += 1
        print(f"  [{r.numero_acordo}] AINDA VAZIO: {campos_vazios} | cliente={repr(r.cliente)} credor={repr(r.credor)}")
    else:
        print(f"  [{r.numero_acordo}] OK: cliente={nome_curto} | credor={r.credor} (cre_id={r.cre_id})")

print(f"\nResumo: {qs.count() - vazios} corrigidos, {vazios} ainda com campos vazios")
