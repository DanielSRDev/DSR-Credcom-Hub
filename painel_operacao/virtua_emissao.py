"""
Acordos (emissao) das carteiras migradas pro Virtua (Firebird), pra entrar
no Relatorio Geral e no Painel Operacao principal ao lado do Stage.

So mexe em LEITURA do Virtua; a gravacao continua em
sincronizar_relatorio_geral()/sincronizar_painel_operacao() (services.py),
que chamam buscar_registros_virtua_para_relatorio()/
buscar_registros_virtua_para_painel() e passam o resultado pras funcoes ja
usadas pro carryover/base do Stage, sem duplicar logica de calculo.

Regra de negocio (confirmada com o usuario 2026-08-10): emissao/pago/quebra/
a-vencer continuam usando so o honorario liquido do acordo (mesma regra do
Stage) -- isso NAO muda com os ajustes abaixo.

Ajuste 2026-08-10 (2a rodada, validado com acordo real 244371/Jardel Mota):
"principal_liquido" passou a vir de OPERACOES.VALORNOMINAL (o "Valor Parcela"
real da tela, ex.: 1.000,00) em vez de VALOR_TOTAL - VALOR_HONORARIO. Como o
Vlr Total Acordo do painel = Valor Parcela + Honorario (formula de 2 termos,
compartilhada com o Stage), e o Virtua tem um 3o componente real
(VALORPROTESTO, ex.: 300,00) que essa formula nao tem onde encaixar, o Vlr
Total Acordo calculado fica ~300 a menos que o VALORDIVIDA real nesses casos
-- prioridade combinada com o usuario: Valor Parcela certo > Vlr Total exato.

Ajuste 2026-08-12: generalizado pra varias carteiras (era so Viver Bem).
Ver CARTEIRAS_VIRTUA (mesmo mapa/mesma logica de
Backoffice_nibo/Backend/services/sync_virtua.py, mas cada projeto tem sua
propria copia do dict -- nao ha import cruzado entre os dois Django).
"""
import re
from datetime import date as _date, datetime as _datetime

# banco (Virtua) -> {credor_id (Nibo/Stage), nome} — cada linha aqui e' uma
# carteira migrada. Pra adicionar mais uma, so incluir aqui.
CARTEIRAS_VIRTUA = {
    2008: {"credor_id": 194298103, "nome": "Viver Bem"},
    2120: {"credor_id": 198948068, "nome": "HB Construtora"},
}

# Prefixo de OPERACOES.NROPERACAO (linha original) -> Tipo de Negociacao.
# Usuario confirmou 2026-08-10 que essa convencao (prefixo + data) vai ficar
# padrao daqui pra frente. Nao reconhecido = fica em branco (nao forca
# aproximacao errada).
PREFIXOS_TIPO_NEGOCIACAO = [
    (re.compile(r"^REFI", re.IGNORECASE), "Refinanciamento"),
    (re.compile(r"^PARC", re.IGNORECASE), "Parcelamento"),
    (re.compile(r"^ATUA", re.IGNORECASE), "Atualização"),
    (re.compile(r"^A\s*VUL", re.IGNORECASE), "Parcela Avulsa"),
]

def _query(qtd_bancos: int) -> str:
    placeholders = ",".join("?" for _ in range(qtd_bancos))
    return f"""
        SELECT
            op.BANCO,
            op.NR_PROPOSTA,
            op.NR_CARTA_ACORDO,
            op.CLIENTE,
            op.VALOR_TOTAL,
            op.VALOR_HONORARIO,
            op.NR_PARCELAS,
            op.SITUACAO,
            op.DTA_CAD,
            op.USR_CAD,
            cli.NOME AS CLIENTE_NOME,
            COALESCE(NULLIF(cli.CPF, ''), NULLIF(cli.CGC, '')) AS CLIENTE_DOC,
            oorig.CONTA,
            oorig.FORMAATUALIZACAO,
            oorig.NROPERACAO,
            oorig.TIPOOPERACAO,
            oorig.VALORNOMINAL,
            oorig.PRAZOPERMPARC,
            usr.NOME AS USUARIO_NOME,
            (SELECT MIN(p1.DATA_VENCIMENTO) FROM OPERACOES_PROPOSTA_PARC p1
              WHERE p1.NR_PROPOSTA = op.NR_PROPOSTA AND p1.CLIENTE = op.CLIENTE) AS DATA_VENCIMENTO,
            (SELECT MAX(p2.DATA_PAGO) FROM OPERACOES_PROPOSTA_PARC p2
              WHERE p2.NR_PROPOSTA = op.NR_PROPOSTA AND p2.CLIENTE = op.CLIENTE) AS DATA_PAGO,
            (SELECT SUM(p3.VALOR_PAGO) FROM OPERACOES_PROPOSTA_PARC p3
              WHERE p3.NR_PROPOSTA = op.NR_PROPOSTA AND p3.CLIENTE = op.CLIENTE
                AND p3.VALOR_PAGO IS NOT NULL) AS VALOR_PAGO_TOTAL
        FROM OPERACOES_PROPOSTA op
        LEFT JOIN CLIENTES cli ON cli.CODIGO = op.CLIENTE
        LEFT JOIN USUARIOS usr ON usr.CODIGO = op.USR_CAD
        LEFT JOIN OPERACOES_PROPOSTA_OPER ooper
            ON ooper.NR_PROPOSTA = op.NR_PROPOSTA AND ooper.CLIENTE = op.CLIENTE
        LEFT JOIN OPERACOES oorig
            ON oorig.CLIENTE = ooper.CLIENTE
           AND oorig.NROPERACAO = ooper.NROPERACAO
           AND oorig.REMESSA = ooper.REMESSA
        WHERE op.BANCO IN ({placeholders})
    """


def _conectar():
    from django.conf import settings
    import firebirdsql

    cfg = settings.VIRTUA_FIREBIRD
    return firebirdsql.connect(
        host=cfg["HOST"],
        database=cfg["DATABASE"],
        user=cfg["USER"],
        password=cfg["PASSWORD"],
        charset=cfg.get("CHARSET", "WIN1252"),
    )


def _para_datetime(valor):
    """DATA_VENCIMENTO/DATA_PAGO vêm como datetime.date puro (sem hora) do
    Firebird; make_aware_if_needed() (services.py) exige datetime.datetime."""
    if valor is None:
        return None
    if isinstance(valor, _datetime):
        return valor
    if isinstance(valor, _date):
        return _datetime(valor.year, valor.month, valor.day)
    return valor


def _valor_br_para_float(texto):
    """PRAZOPERMPARC vem como texto BR ('5.087,13'); None/vazio -> None."""
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return float(texto.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _classificar_tipo_negociacao(nroperacao):
    texto = (nroperacao or "").strip()
    if not texto:
        return ""
    for regex, nome in PREFIXOS_TIPO_NEGOCIACAO:
        if regex.match(texto):
            return nome
    return ""


CONECTIVOS_NOME = {"de", "da", "do", "das", "dos", "e"}


def _titulo_nome(nome):
    """
    Virtua grava nome de usuário/cliente em CAIXA ALTA (ex.: "LUCAS ASCHINELLI
    ROMANO"). Formata em Título, mantendo conectivos (de/da/do/dos/das/e) em
    minúsculo -- exceto quando é a primeira palavra.
    """
    nome = (nome or "").strip()
    if not nome:
        return ""
    palavras = nome.lower().split()
    formatado = [
        palavra if (palavra in CONECTIVOS_NOME and i > 0) else palavra.capitalize()
        for i, palavra in enumerate(palavras)
    ]
    return " ".join(formatado)


def _buscar_linhas_base(data_ini, data_fim):
    """
    Le os acordos de TODAS as carteiras em CARTEIRAS_VIRTUA e devolve os
    campos comuns já calculados (honorário, principal/nominal, tipo de
    negociação, valor recuperado, datas, carteira), filtrados por
    DATA_VENCIMENTO (= data_acordo) dentro de [data_ini, data_fim] -- mesma
    âncora usada pelo base_hub do Stage.

    Usado tanto por buscar_registros_virtua_para_relatorio() (Relatório
    Geral/Acompanhamento) quanto por buscar_registros_virtua_para_painel()
    (Painel Operação/tela principal) -- mesma leitura do Virtua, só muda o
    formato final do dict pra cada consumidor.
    """
    bancos = list(CARTEIRAS_VIRTUA.keys())
    con = _conectar()
    try:
        cur = con.cursor()
        cur.execute(_query(len(bancos)), tuple(bancos))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        con.close()

    linhas = []
    for r in rows:
        row = dict(zip(cols, r))

        nr_carta_acordo = row["NR_CARTA_ACORDO"]
        data_vencimento = row["DATA_VENCIMENTO"]
        if nr_carta_acordo is None or data_vencimento is None:
            continue
        if not (data_ini <= data_vencimento <= data_fim):
            continue

        aco_id = int(round(nr_carta_acordo))
        valor_honorario = float(row["VALOR_HONORARIO"] or 0)
        principal_liquido = float(row["VALORNOMINAL"] or 0)
        tipo_negociacao = _classificar_tipo_negociacao(row["NROPERACAO"])
        valor_recuperado = _valor_br_para_float(row["PRAZOPERMPARC"])
        carteira = CARTEIRAS_VIRTUA[row["BANCO"]]

        linhas.append({
            "row": row,
            "aco_id": aco_id,
            "carteira": carteira,
            "data_acordo": _para_datetime(data_vencimento),
            "data_emissao": _para_datetime(row["DTA_CAD"]),
            "data_pagamento": _para_datetime(row["DATA_PAGO"]),
            "valor_honorario": valor_honorario,
            "principal_liquido": principal_liquido,
            "tipo_negociacao": tipo_negociacao,
            "valor_recuperado_parcelamento": valor_recuperado if tipo_negociacao == "Parcelamento" else None,
            "valor_recuperado_refinanciamento": valor_recuperado if tipo_negociacao == "Refinanciamento" else None,
        })

    return linhas


def buscar_registros_virtua_para_relatorio(data_ini, data_fim):
    """
    Devolve uma lista de dicts no formato aceito por
    painel_operacao.services.criar_registros_relatorio_geral (mesmo formato
    usado hoje pro carryover do Stage) -- alimenta Relatório Geral e
    Acompanhamento Geral.
    """
    registros = []
    for item in _buscar_linhas_base(data_ini, data_fim):
        row = item["row"]
        carteira = item["carteira"]
        registros.append({
            "origem_registro": "VIRTUA",
            "data_acordo": item["data_acordo"],
            "data_emissao": item["data_emissao"],
            "data_pagamento": item["data_pagamento"],
            "numero_acordo": str(item["aco_id"]),
            "aco_id": item["aco_id"],
            "contrato": row["CONTA"] or "",
            "con_id": None,
            "observacao_contrato": row["FORMAATUALIZACAO"] or "",
            "cliente": row["CLIENTE_NOME"] or "",
            "cpf_cnpj": row["CLIENTE_DOC"] or "",
            "cre_id": carteira["credor_id"],
            "credor": carteira["nome"],
            "filial": row["TIPOOPERACAO"] or "",
            "tipo_contrato": carteira["nome"],
            "tipo_negociacao": item["tipo_negociacao"],
            "honorario_bruto": item["valor_honorario"],
            "desconto_honorario": 0,
            "honorario_liquido": item["valor_honorario"],
            "principal_liquido": item["principal_liquido"],
            "multa_liquida": 0,
            "juros_liquido": 0,
            "despesas": 0,
            "despesa_liquida": 0,
            "taxa_liquida": 0,
            "valor_recuperado_parcelamento": item["valor_recuperado_parcelamento"],
            "valor_recuperado_refinanciamento": item["valor_recuperado_refinanciamento"],
            "valor_pago_periodo": float(row["VALOR_PAGO_TOTAL"] or 0),
            "qtd_parcelas_acordo": row["NR_PARCELAS"] or 0,
            "status_acordo": row["SITUACAO"] or "",
            "tipo_acordo": "",
            "emitido_por_login": _titulo_nome(row["USUARIO_NOME"]),
        })

    return registros


def buscar_registros_virtua_para_painel(data_ini, data_fim):
    """
    Devolve (registros_acordo_raw, aco_ids_pagos) no formato aceito por
    painel_operacao.services.criar_registros_locais() -- alimenta a tela
    principal "Painel Operação" (PainelOperacaoRegistro), separada do
    Relatório Geral/Acompanhamento.
    """
    registros = []
    aco_ids_pagos = set()

    for item in _buscar_linhas_base(data_ini, data_fim):
        row = item["row"]
        aco_id = item["aco_id"]
        carteira = item["carteira"]
        if item["data_pagamento"] is not None:
            aco_ids_pagos.add(aco_id)

        registros.append({
            "numero_acordo": str(aco_id),
            "aco_id": aco_id,
            "data_acordo": item["data_acordo"],
            "data_emissao": item["data_emissao"],
            "data_etl_alteracao": item["data_emissao"],
            "cliente": row["CLIENTE_NOME"] or "",
            "cpf_cnpj": row["CLIENTE_DOC"] or "",
            "contrato": row["CONTA"] or "",
            "con_id": None,
            "cre_id": carteira["credor_id"],
            "credor": carteira["nome"],
            "observacao_contrato": row["FORMAATUALIZACAO"] or "",
            "filial": row["TIPOOPERACAO"] or "",
            "tipo_contrato": carteira["nome"],
            "tipo_negociacao": item["tipo_negociacao"],
            "principal_bruto": item["principal_liquido"],
            "desconto_principal": 0,
            "principal_liquido": item["principal_liquido"],
            "multa_bruta": 0,
            "desconto_multa": 0,
            "multa_liquida": 0,
            "juros_bruto": 0,
            "desconto_juros": 0,
            "juros_liquido": 0,
            "honorario_bruto": item["valor_honorario"],
            "desconto_honorario": 0,
            "honorario_liquido": item["valor_honorario"],
            "despesas": 0,
            "despesa_liquida": 0,
            "taxa_liquida": 0,
            "subtotal_bruto": item["principal_liquido"] + item["valor_honorario"],
            "desconto_total": 0,
            "valor_total_liquido": item["principal_liquido"] + item["valor_honorario"],
            "valor_entrada": 0,
            "qtd_parcelas_acordo": row["NR_PARCELAS"] or 0,
            "status_acordo": row["SITUACAO"] or "",
            "tipo_acordo": "",
            "emitido_por": _titulo_nome(row["USUARIO_NOME"]),
        })

    return registros, aco_ids_pagos
