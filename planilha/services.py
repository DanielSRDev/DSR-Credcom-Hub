"""
Importação de bases para o módulo Planilha.

Fluxo:
  1) upload do .xlsx -> salvo em MEDIA/planilha_tmp/<token>.xlsx
  2) ler_planilha + validar -> tela de pré-visualização com alerta
  3) se aprovado -> importar (versiona: gera Excel da base antiga e substitui)
"""
from __future__ import annotations

import os
import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.db import transaction

from .models import (
    PlanilhaContrato,
    PlanilhaImportacao,
    PlanilhaImportLog,
)

SHEET = "Operador"

COL = {
    "carteira": "Carteira",
    "cre_id": "Codigo",
    "operador": "Operador",
    "nr_contrato": "Nr Contrato",
    "tipo_contrato": "Tipo do Contrato",
    "empreendimento": "Empreendimento",
    "atraso": "Atraso real",
    "vlr_total": "Vlr total",
    "status_antigo": "Status Antigo",
    "cpf_cnpj": "CPFCNPJ",
    "nome": "Nome",
    "status_atual": "Status Atual",
}

# Colunas OPCIONAIS: só algumas bases trazem (ex.: a de obras, com CodEmpresa/
# CodObra). Não entram na checagem de "coluna faltando" — se não existirem no
# arquivo, ficam em branco.
COL_OPCIONAIS = {
    "cod_empresa": "CodEmpresa",
    "cod_obra": "CodObra",
}

TMP_DIR = Path(settings.MEDIA_ROOT) / "planilha_tmp"
DEVOLUCAO_DIR = Path(settings.MEDIA_ROOT) / "planilha_devolucoes"


# ─────────────────────────── helpers ────────────────────────────
def so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def limpar(valor) -> str:
    if valor is None:
        return ""
    s = str(valor).strip()
    return "" if s.lower() == "nan" else s


def parse_decimal(valor) -> Decimal:
    s = limpar(valor)
    if not s:
        return Decimal("0.00")
    s = s.replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        # formato BR: 1.234,56  -> ponto = milhar, vírgula = decimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def parse_int(valor):
    s = limpar(valor)
    if not s:
        return None
    try:
        return int(float(s.replace(",", ".")))
    except (ValueError, TypeError):
        return None


def _nome_arquivo_seguro(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", texto).strip("_") or "base"


# ─────────────────────────── upload temp ────────────────────────
def salvar_upload_tmp(arquivo) -> str:
    """Salva o arquivo enviado em MEDIA/planilha_tmp e devolve o token (uuid)."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    destino = TMP_DIR / f"{token}.xlsx"
    with open(destino, "wb") as f:
        for chunk in arquivo.chunks():
            f.write(chunk)
    return token


def caminho_tmp(token: str) -> Path:
    # token só pode ser hex (uuid) — evita path traversal
    if not re.fullmatch(r"[0-9a-fA-F]{32}", token or ""):
        raise ValueError("Token inválido.")
    return TMP_DIR / f"{token}.xlsx"


def remover_tmp(token: str) -> None:
    try:
        caminho_tmp(token).unlink(missing_ok=True)
    except Exception:
        pass


# ─────────────────────────── leitura ────────────────────────────
def ler_planilha(caminho) -> list[dict]:
    """Lê a aba 'Operador' e devolve a lista de linhas normalizadas."""
    xl = pd.ExcelFile(caminho)
    if SHEET not in xl.sheet_names:
        raise ValueError(
            f"A planilha precisa ter a aba '{SHEET}'. Abas encontradas: {', '.join(xl.sheet_names)}."
        )
    df = xl.parse(SHEET, dtype=str)

    faltando = [nome for chave, nome in COL.items()
                if chave != "status_atual" and nome not in df.columns]
    if faltando:
        raise ValueError("Colunas faltando na aba 'Operador': " + ", ".join(faltando))

    linhas = []
    for _, row in df.iterrows():
        cre_id = parse_int(row.get(COL["cre_id"]))
        operador = limpar(row.get(COL["operador"]))
        nr_contrato = limpar(row.get(COL["nr_contrato"]))
        cpf = limpar(row.get(COL["cpf_cnpj"]))
        nome = limpar(row.get(COL["nome"]))

        # ignora linhas totalmente vazias
        if not any([cre_id, operador, nr_contrato, cpf, nome]):
            continue

        linhas.append({
            "carteira": limpar(row.get(COL["carteira"])),
            "cre_id": cre_id,
            "operador": operador,
            "nr_contrato": nr_contrato,
            "tipo_contrato": limpar(row.get(COL["tipo_contrato"])),
            "empreendimento": limpar(row.get(COL["empreendimento"])),
            "atraso": parse_int(row.get(COL["atraso"])),
            "vlr_total": parse_decimal(row.get(COL["vlr_total"])),
            "status_antigo": limpar(row.get(COL["status_antigo"])),
            "cpf_cnpj": cpf,
            "cpf_digitos": so_digitos(cpf),
            "nome": nome,
            "cod_empresa": limpar(row.get(COL_OPCIONAIS["cod_empresa"])),
            "cod_obra": limpar(row.get(COL_OPCIONAIS["cod_obra"])),
        })
    return linhas


# ─────────────────────────── validação ──────────────────────────
def validar(linhas: list[dict]) -> dict:
    """Analisa as linhas e retorna resumo + inconsistências (sem gravar nada)."""
    por_carteira = defaultdict(lambda: {"nome": "", "operadores": set(), "contratos": 0})
    cpf_operadores = defaultdict(set)   # (cre_id, cpf_digitos) -> {operadores}
    cpf_info = {}                        # (cre_id, cpf_digitos) -> {nome, contratos}
    contrato_reg = defaultdict(lambda: {"qtd": 0, "nome": "", "operadores": set()})  # (cre_id, nr_contrato)
    linhas_invalidas = 0

    for ln in linhas:
        cre_id = ln["cre_id"]
        if not cre_id or not ln["operador"]:
            linhas_invalidas += 1
            continue

        c = por_carteira[cre_id]
        c["nome"] = ln["carteira"] or c["nome"]
        c["operadores"].add(ln["operador"])
        c["contratos"] += 1

        if ln["cpf_digitos"]:
            chave = (cre_id, ln["cpf_digitos"])
            cpf_operadores[chave].add(ln["operador"])
            info = cpf_info.setdefault(chave, {"nome": ln["nome"], "contratos": 0})
            info["contratos"] += 1

        # Nr Contrato é único: contar repetições para acusar contrato duplicado.
        if ln["nr_contrato"]:
            d = contrato_reg[(cre_id, ln["nr_contrato"])]
            d["qtd"] += 1
            d["nome"] = d["nome"] or ln["nome"]
            d["operadores"].add(ln["operador"])

    # CPF com mais de um operador
    cpf_multi = []
    for (cre_id, cpf_dig), operadores in cpf_operadores.items():
        if len(operadores) > 1:
            info = cpf_info[(cre_id, cpf_dig)]
            cpf_multi.append({
                "cre_id": cre_id,
                "cpf": cpf_dig,
                "nome": info["nome"],
                "operadores": sorted(operadores),
                "contratos": info["contratos"],
            })
    cpf_multi.sort(key=lambda x: (-len(x["operadores"]), x["nome"]))

    # Nr Contrato repetido (contrato existe só uma vez)
    contratos_duplicados = [
        {"cre_id": cre_id, "nr_contrato": nr, "qtd": d["qtd"],
         "nome": d["nome"], "operadores": sorted(d["operadores"])}
        for (cre_id, nr), d in contrato_reg.items() if d["qtd"] > 1
    ]
    contratos_duplicados.sort(key=lambda x: (-x["qtd"], x["nr_contrato"]))

    carteiras = [
        {"cre_id": cre_id, "nome": d["nome"],
         "operadores": sorted(d["operadores"]), "qtd_operadores": len(d["operadores"]),
         "contratos": d["contratos"]}
        for cre_id, d in sorted(por_carteira.items(), key=lambda kv: kv[1]["nome"])
    ]

    cre_ids = [c["cre_id"] for c in carteiras]
    existentes = {
        imp.cre_id: imp
        for imp in PlanilhaImportacao.objects.filter(cre_id__in=cre_ids)
    }

    # Nr Contrato por cre_id no arquivo novo, pra comparar com o que já existe
    # e permitir a opção "adicionar só os novos" em vez de substituir tudo.
    nr_contratos_arquivo = defaultdict(set)
    for ln in linhas:
        if ln["cre_id"] and ln["nr_contrato"]:
            nr_contratos_arquivo[ln["cre_id"]].add(ln["nr_contrato"])

    substituicoes = []
    for imp in existentes.values():
        nr_contratos_atuais = set(
            PlanilhaContrato.objects.filter(cre_id=imp.cre_id).values_list("nr_contrato", flat=True)
        )
        nr_contratos_novo_arquivo = nr_contratos_arquivo.get(imp.cre_id, set())
        contratos_novos = nr_contratos_novo_arquivo - nr_contratos_atuais
        substituicoes.append({
            "cre_id": imp.cre_id,
            "nome": imp.carteira_nome,
            "total_atual": imp.total_contratos,
            "contratos_novos": len(contratos_novos),
            "contratos_ja_existentes": len(nr_contratos_novo_arquivo & nr_contratos_atuais),
        })

    tem_inconsistencia = bool(cpf_multi) or bool(contratos_duplicados) or linhas_invalidas > 0

    return {
        "resumo": {
            "total_linhas": len(linhas),
            "total_validas": len(linhas) - linhas_invalidas,
            "carteiras": carteiras,
            "total_contratos": sum(c["contratos"] for c in carteiras),
        },
        "substituicoes": substituicoes,
        "cpf_multi_operador": cpf_multi,
        "contratos_duplicados": contratos_duplicados,
        "linhas_invalidas": linhas_invalidas,
        "tem_inconsistencia": tem_inconsistencia,
    }


# ─────────────────────── Excel da base antiga ───────────────────
def gerar_excel_base_antiga(cre_id: int) -> str:
    """
    Exporta os contratos ATUAIS de um cre_id no mesmo modelo (12 colunas)
    para MEDIA/planilha_devolucoes e devolve o nome do arquivo.

    Antes de montar a planilha, busca no Virtua o Status Atual mais recente
    desses contratos — assim a base devolvida sai com o status na hora da
    reimportação, não com o que ficou salvo na última sincronização (que
    pode ter até PLANILHA_SYNC_STATUS_MINUTOS de atraso). Se o Virtua estiver
    fora do ar, não trava a reimportação — segue com o status já salvo.
    """
    qs = PlanilhaContrato.objects.filter(cre_id=cre_id)
    try:
        _sincronizar_status_virtua_qs(qs)
    except Exception as e:
        print(f"[planilha] Falha ao atualizar Status Atual antes da devolução (cre_id={cre_id}):", e)

    dados = [{
        "Carteira": c.carteira_nome,
        "Codigo": c.cre_id,
        "Operador": c.operador_nome,
        "Nr Contrato": c.nr_contrato,
        "Tipo do Contrato": c.tipo_contrato,
        "Empreendimento": c.empreendimento,
        "Atraso real": c.atraso_real,
        "Vlr total": float(c.vlr_total or 0),
        "Status Antigo": c.status_antigo,
        "CPFCNPJ": c.cpf_cnpj,
        "Nome": c.nome_cliente,
        "Status Atual": c.status_atual,
        "CodEmpresa": c.cod_empresa,
        "CodObra": c.cod_obra,
    } for c in qs]

    DEVOLUCAO_DIR.mkdir(parents=True, exist_ok=True)
    carteira = qs.first().carteira_nome if qs.exists() else str(cre_id)
    nome = f"{_nome_arquivo_seguro(carteira)}_{cre_id}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    caminho = DEVOLUCAO_DIR / nome

    df = pd.DataFrame(dados, columns=list(COL.values()) + list(COL_OPCIONAIS.values()))
    with pd.ExcelWriter(caminho, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Operador", index=False)
    return nome


def caminho_devolucao(nome: str) -> Path:
    # só nome de arquivo simples (sem separadores) — evita path traversal
    if not nome or "/" in nome or "\\" in nome or ".." in nome:
        raise ValueError("Arquivo inválido.")
    return DEVOLUCAO_DIR / nome


# ─────────────────────────── importação ─────────────────────────
def _linha_para_contrato(imp, cre_id, carteira_nome, r) -> "PlanilhaContrato":
    return PlanilhaContrato(
        importacao=imp,
        cre_id=cre_id,
        carteira_nome=r["carteira"] or carteira_nome,
        operador_nome=r["operador"],
        nr_contrato=r["nr_contrato"],
        tipo_contrato=r["tipo_contrato"],
        empreendimento=r["empreendimento"],
        atraso_real=r["atraso"],
        vlr_total=r["vlr_total"],
        status_antigo=r["status_antigo"],
        cpf_cnpj=r["cpf_cnpj"],
        nome_cliente=r["nome"],
        cod_empresa=r["cod_empresa"],
        cod_obra=r["cod_obra"],
    )


def importar(linhas: list[dict], user, importado_mesmo_com_erros: bool,
             inconsistencias: int = 0, arquivo_nome: str = "",
             modo: str = "substituir") -> list[dict]:
    """
    Grava a base por cre_id, em dois modos possíveis:

    - modo="substituir" (padrão, comportamento de sempre): para cada cre_id
      já existente, gera o Excel da base antiga (devolução) e apaga a antiga
      antes de inserir a nova (prioridade/destaque/fila/acréscimos da base
      antiga se perdem).
    - modo="adicionar": NÃO apaga nada da base existente. Insere só os
      contratos cujo Nr Contrato ainda não está na base atual daquele cre_id
      (contratos que já existem são ignorados, sem atualizar valores). Se o
      cre_id ainda não tem base, comporta-se igual a "substituir" (não tem
      o que preservar).

    Retorna a lista de resultados por carteira.
    """
    por_cre = defaultdict(list)
    for ln in linhas:
        if ln["cre_id"] and ln["operador"]:
            por_cre[ln["cre_id"]].append(ln)

    resultados = []

    for cre_id, rows in por_cre.items():
        carteira_nome = next((r["carteira"] for r in rows if r["carteira"]), str(cre_id))
        arquivo_devolvido = ""
        removidos = 0
        ignorados_ja_existentes = 0

        with transaction.atomic():
            existente = PlanilhaImportacao.objects.filter(cre_id=cre_id).first()

            if existente and modo == "adicionar":
                nr_contratos_atuais = set(
                    PlanilhaContrato.objects.filter(cre_id=cre_id).values_list("nr_contrato", flat=True)
                )
                rows_novas = [r for r in rows if r["nr_contrato"] not in nr_contratos_atuais]
                ignorados_ja_existentes = len(rows) - len(rows_novas)

                imp = existente
                contratos = [_linha_para_contrato(imp, cre_id, carteira_nome, r) for r in rows_novas]
                if contratos:
                    PlanilhaContrato.objects.bulk_create(contratos, batch_size=1000)
                    imp.total_contratos = imp.contratos.count()
                    imp.arquivo_nome = arquivo_nome
                    imp.save(update_fields=["total_contratos", "arquivo_nome"])

                PlanilhaImportLog.objects.create(
                    cre_id=cre_id,
                    carteira_nome=carteira_nome,
                    importado_por=user if getattr(user, "is_authenticated", False) else None,
                    total_inseridos=len(contratos),
                    total_removidos=0,
                    inconsistencias=inconsistencias,
                    importado_mesmo_com_erros=importado_mesmo_com_erros,
                    arquivo_devolvido="",
                )

                resultados.append({
                    "cre_id": cre_id,
                    "carteira": carteira_nome,
                    "inseridos": len(contratos),
                    "removidos": 0,
                    "ignorados_ja_existentes": ignorados_ja_existentes,
                    "substituiu": False,
                    "adicionou": True,
                    "arquivo_devolvido": "",
                })
                continue

            if existente:
                arquivo_devolvido = gerar_excel_base_antiga(cre_id)
                removidos = existente.contratos.count()
                existente.delete()  # cascade apaga os contratos antigos

            imp = PlanilhaImportacao.objects.create(
                cre_id=cre_id,
                carteira_nome=carteira_nome,
                arquivo_nome=arquivo_nome,
                importado_por=user if getattr(user, "is_authenticated", False) else None,
                total_contratos=len(rows),
            )

            contratos = [_linha_para_contrato(imp, cre_id, carteira_nome, r) for r in rows]
            PlanilhaContrato.objects.bulk_create(contratos, batch_size=1000)

            PlanilhaImportLog.objects.create(
                cre_id=cre_id,
                carteira_nome=carteira_nome,
                importado_por=user if getattr(user, "is_authenticated", False) else None,
                total_inseridos=len(rows),
                total_removidos=removidos,
                inconsistencias=inconsistencias,
                importado_mesmo_com_erros=importado_mesmo_com_erros,
                arquivo_devolvido=arquivo_devolvido,
            )

        resultados.append({
            "cre_id": cre_id,
            "carteira": carteira_nome,
            "inseridos": len(rows),
            "removidos": removidos,
            "ignorados_ja_existentes": 0,
            "substituiu": bool(arquivo_devolvido),
            "adicionou": False,
            "arquivo_devolvido": arquivo_devolvido,
        })

    return resultados


# ─────────────────────── exportar selecionados ──────────────────
def montar_xlsx_contratos(qs) -> bytes:
    """
    Gera um Excel dos contratos do queryset, incluindo os acréscimos
    (telefone/e-mail/nota) que o operador inseriu, agregados por contrato.
    """
    from io import BytesIO

    qs = qs.prefetch_related("acrescimos")
    linhas = []
    for c in qs:
        tel, mail, nota = [], [], []
        for a in c.acrescimos.all():
            if a.tipo == "telefone":
                tel.append(a.valor)
            elif a.tipo == "email":
                mail.append(a.valor)
            else:
                nota.append(a.valor)
        linhas.append({
            "Carteira": c.carteira_nome,
            "Codigo": c.cre_id,
            "Operador": c.operador_nome,
            "Nr Contrato": c.nr_contrato,
            "Tipo do Contrato": c.tipo_contrato,
            "Empreendimento": c.empreendimento,
            "Atraso real": c.atraso_real,
            "Vlr total": float(c.vlr_total or 0),
            "Status Antigo": c.status_antigo,
            "CPFCNPJ": c.cpf_cnpj,
            "Nome": c.nome_cliente,
            "Status Atual": c.status_atual,
            "CodEmpresa": c.cod_empresa,
            "CodObra": c.cod_obra,
            "Prioridade": "Sim" if c.prioridade else "",
            "Telefones (acréscimo)": " ; ".join(tel),
            "E-mails (acréscimo)": " ; ".join(mail),
            "Notas (acréscimo)": " ; ".join(nota),
        })

    colunas = [
        "Carteira", "Codigo", "Operador", "Nr Contrato", "Tipo do Contrato",
        "Empreendimento", "Atraso real", "Vlr total", "Status Antigo", "CPFCNPJ",
        "Nome", "Status Atual", "CodEmpresa", "CodObra", "Prioridade",
        "Telefones (acréscimo)", "E-mails (acréscimo)", "Notas (acréscimo)",
    ]
    df = pd.DataFrame(linhas, columns=colunas)
    out = BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Selecionados", index=False)
    out.seek(0)
    return out.read()


# --- lock em arquivo (mesmo padrão do envio Nibo em nibo_panel/services/remessa.py) ---
# evita que o botão "atualizar agora" rode em cima da sincronização automática
# (ou de dois cliques seguidos) ao mesmo tempo, batendo no Virtua em paralelo.
LOCK_SYNC_STATUS_STALE_MINUTOS = 15  # acima disso, considera o lock "órfão" e toma posse


def _lock_sync_status_path() -> Path:
    base = Path(getattr(settings, "BASE_DIR", Path(".")))
    return base / "var" / "planilha_sync_status.lock"


def adquirir_lock_sync_status() -> bool:
    from datetime import datetime as _dt

    p = _lock_sync_status_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"pid={os.getpid()} em={_dt.now().isoformat()}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            idade_min = (_dt.now().timestamp() - p.stat().st_mtime) / 60
        except OSError:
            return False
        if idade_min <= LOCK_SYNC_STATUS_STALE_MINUTOS:
            return False
        try:
            p.unlink()
        except OSError:
            return False
        return adquirir_lock_sync_status()


def liberar_lock_sync_status():
    try:
        _lock_sync_status_path().unlink()
    except OSError:
        pass


def _sincronizar_status_virtua_qs(qs) -> dict:
    """
    Atualiza status_atual/status_atual_data (com o último evento do Virtua
    DENTRO DO MÊS CORRENTE) dos contratos do queryset informado.

    Contrato sem evento no mês corrente fica com o Status Atual VAZIO (não
    arrasta status de mês anterior) — por isso percorre TODO o queryset, não
    só quem apareceu na consulta ao Virtua. Só grava quem realmente mudou.
    """
    from django.utils import timezone

    from . import virtua

    nr_contratos = list(qs.values_list("nr_contrato", flat=True).distinct())
    if not nr_contratos:
        return {"total_base": 0, "encontrados": 0, "atualizados": 0, "limpos": 0}

    eventos = virtua.buscar_status_atual(nr_contratos)  # já restrito ao mês corrente

    atualizar = []
    limpos = 0
    for c in qs.only("id", "nr_contrato", "status_atual", "status_atual_data"):
        desc, datahora = eventos.get(c.nr_contrato, (None, None))
        if datahora and timezone.is_naive(datahora):
            datahora = timezone.make_aware(datahora)
        novo_status = desc or ""
        if c.status_atual != novo_status or c.status_atual_data != datahora:
            if not novo_status and c.status_atual:
                limpos += 1
            c.status_atual = novo_status
            c.status_atual_data = datahora
            atualizar.append(c)

    if atualizar:
        PlanilhaContrato.objects.bulk_update(atualizar, ["status_atual", "status_atual_data"])

    return {
        "total_base": len(nr_contratos),
        "encontrados": len(eventos),
        "atualizados": len(atualizar),
        "limpos": limpos,
    }


def sincronizar_status_virtua() -> dict:
    """Sincroniza o Status Atual de TODA a base com o Virtua."""
    return _sincronizar_status_virtua_qs(PlanilhaContrato.objects.all())
