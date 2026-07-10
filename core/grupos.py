"""
Fonte única dos nomes de cargo (grupos do Django) do sistema.

Use SEMPRE estas constantes em vez de digitar a string do grupo no código —
evita os erros de grafia que existiam antes (ex.: OPERACAO_CORDENACAO escrito
de 3 formas diferentes em arquivos distintos).

Modelo-alvo da reestruturação de cargos (ver memória do projeto):
6 cargos canônicos. A migração de regras (middleware/views/chat) para estes
cargos é feita em etapas — enquanto não concluída, parte do código ainda
referencia os grupos legados listados em LEGADOS.
"""

# ── Cargos canônicos (modelo-alvo) ───────────────────────────────────────────
GESTAO        = "GESTAO"          # Diretoria — vê tudo
GESTAO_GESTOR = "GESTAO_GESTOR"   # Gestor / líder de equipe (supervisor da Operação)
POS_ACORDO    = "POS_ACORDO"      # Gerência na Operação, dentro da equipe do supervisor
OPERACAO      = "OPERACAO"        # Operador comum (pertence a uma equipe)
FINANCEIRO    = "FINANCEIRO"      # Nibo + Financeiro
JURIDICO      = "JURIDICO"        # Equipe jurídico (base Operação; alguns liberam Gestão)

# Lista oficial dos cargos do sistema.
CARGOS = [GESTAO, GESTAO_GESTOR, POS_ACORDO, OPERACAO, FINANCEIRO, JURIDICO]

# ── Grupos legados (em remoção) ──────────────────────────────────────────────
# Ainda usados pelo código não migrado. Não criar novas referências a estes.
LEGADOS = [
    "GESTAO_GESTORA",
    "GESTAO_USUARIO",
    "NIBO",
    "OPERACAO_SUPERVISOR",
    "OPERACAO_CORDENACAO",
]
