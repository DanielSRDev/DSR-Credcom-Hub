"""
Acesso (somente leitura) ao banco Firebird do sistema legado Virtua (cobrança).

Usado para trazer o "Status Atual" de cada contrato: o último evento de
cobrança lançado no Virtua (tabela EVENTOSCOBRANCA), casando pelo número da
operação (Virtua: NROPERACAO == nosso PlanilhaContrato.nr_contrato).

Só considera eventos do MÊS CORRENTE (regra do usuário: virou o mês, se não
houve acionamento novo o Status Atual deve voltar a ficar vazio, não arrastar
o status do mês anterior).
"""
from __future__ import annotations

from django.conf import settings

# Nº de parâmetros por consulta (evita estourar limite de statement do Firebird).
TAMANHO_LOTE = 400

# COD_EVENTO que NÃO contam como acionamento pro "Status Atual" (planilha
# "Eventos Virtua - Correção Daniel", marcados de vermelho pelo usuário
# 2026-08-12 — confirmação de pagamento, envio de e-mail/SMS, eventos
# automáticos de bureau/SERASA/SPC/blocklist, etc.). Ao buscar o último
# evento, esses são pulados e pega-se o próximo elegível (mais recente,
# fora dessa lista); se não sobrar nenhum no mês, fica vazio (= não
# acionado), igual já acontecia quando não havia evento nenhum.
COD_EVENTOS_IGNORADOS = (
    8, 20, 21, 22,
    9000, 9001, 9002, 9003, 9004, 9005, 9006, 9007, 9008, 9009,
    9010, 9011, 9012, 9013, 9014, 9015, 9016, 9017, 9018, 9019,
    9020, 9021, 9022, 9023, 9024, 9025, 9026, 9027, 9028, 9029,
    9030, 9031, 9032, 9033, 9034, 9035, 9036, 9037, 9038, 9039,
)


def _conectar():
    import firebirdsql

    cfg = settings.VIRTUA_FIREBIRD
    return firebirdsql.connect(
        host=cfg["HOST"],
        database=cfg["DATABASE"],
        user=cfg["USER"],
        password=cfg["PASSWORD"],
        charset=cfg.get("CHARSET", "WIN1252"),
    )


def _limites_mes_atual():
    """Início (dia 1, 00:00) e fim (dia 1 do mês seguinte) do mês corrente,
    em horário local (naive — o Virtua grava DATAHORA sem timezone)."""
    from django.utils import timezone

    inicio = timezone.localtime(timezone.now()).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if inicio.month == 12:
        fim = inicio.replace(year=inicio.year + 1, month=1)
    else:
        fim = inicio.replace(month=inicio.month + 1)
    return inicio.replace(tzinfo=None), fim.replace(tzinfo=None)


def _buscar_lote(cur, nr_contratos: list[str], inicio_mes, fim_mes) -> dict[str, tuple[str, "datetime.datetime"]]:
    placeholders = ",".join("?" for _ in nr_contratos)
    ignorados_ph = ",".join("?" for _ in COD_EVENTOS_IGNORADOS)
    sql = f"""
        SELECT e.NROPERACAO, e.DATAHORA, c.DESC_EVENTO
        FROM EVENTOSCOBRANCA e
        LEFT JOIN EVENTOS_COD c ON c.COD_EVENTO = e.COD_EVENTO
        WHERE e.NROPERACAO IN ({placeholders})
          AND e.DATAHORA >= ? AND e.DATAHORA < ?
          AND e.COD_EVENTO NOT IN ({ignorados_ph})
          AND e.DATAHORA = (
              SELECT MAX(e2.DATAHORA) FROM EVENTOSCOBRANCA e2
              WHERE e2.NROPERACAO = e.NROPERACAO
                AND e2.DATAHORA >= ? AND e2.DATAHORA < ?
                AND e2.COD_EVENTO NOT IN ({ignorados_ph})
          )
    """
    params = (
        tuple(nr_contratos) + (inicio_mes, fim_mes) + COD_EVENTOS_IGNORADOS
        + (inicio_mes, fim_mes) + COD_EVENTOS_IGNORADOS
    )
    cur.execute(sql, params)
    resultado = {}
    for nroperacao, datahora, desc_evento in cur.fetchall():
        resultado[(nroperacao or "").strip()] = ((desc_evento or "").strip(), datahora)
    return resultado


def buscar_status_atual(nr_contratos: list[str]) -> dict[str, tuple[str, "datetime.datetime"]]:
    """
    Consulta o último evento de cobrança de cada contrato informado,
    considerando só eventos lançados dentro do mês corrente.

    Retorna {nr_contrato: (descricao_evento, data_hora)}. Contratos sem
    evento no mês corrente simplesmente não aparecem no dict (o chamador
    deve tratar isso como "sem status atual").
    """
    nr_contratos = sorted({(n or "").strip() for n in nr_contratos if (n or "").strip()})
    if not nr_contratos:
        return {}

    inicio_mes, fim_mes = _limites_mes_atual()

    resultado: dict[str, tuple[str, "datetime.datetime"]] = {}
    con = _conectar()
    try:
        cur = con.cursor()
        for i in range(0, len(nr_contratos), TAMANHO_LOTE):
            lote = nr_contratos[i:i + TAMANHO_LOTE]
            resultado.update(_buscar_lote(cur, lote, inicio_mes, fim_mes))
    finally:
        con.close()
    return resultado
