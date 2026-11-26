"""Peças comuns a todas as seguradoras.

Cada seguradora é uma classe com dois passos:
  1. baixar(page)        -> entra no portal e baixa o relatório (Excel/CSV/PDF)
  2. normalizar(arquivo) -> converte o relatório para o formato padrão (COLUNAS)
"""
from __future__ import annotations

import io
import re
import warnings
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

# Formato padrão da planilha consolidada (uma linha = uma parcela em aberto).
# As primeiras colunas seguem o modelo da equipe
# (CONTROLE_INADIMPLENCIA.xlsx). PAGAMENTO, PRODUTOR, NOVA DATA, CONTATO e
# DATA LIMITE são de controle interno e saem em branco para preenchimento.
COLUNAS_MODELO = [
    "SEGURADORA",
    "SEGURADO",
    "APÓLICE",      # no modelo era uma coluna só (APÓLICE/CPF); aqui ficam separadas
    "CPF/CNPJ",
    "PAGAMENTO",
    "PARCELA",
    "VENCIMENTO",
    "PRODUTOR",
    "NOVA DATA",
    "CONTATO",
    "DATA LIMITE",
]
# Colunas extras que o robô consegue trazer dos portais
COLUNAS_EXTRAS = [
    "TELEFONE",
    "SITUAÇÃO",     # situação informada pela seguradora (ex.: Atrasado, Recusada)
    "RECIBO",
    "RAMO",
    "DIAS EM ATRASO",
    "VALOR",
    "PREV. CANCELAMENTO",
    "COMISSÃO",
]
COLUNAS = COLUNAS_MODELO + COLUNAS_EXTRAS


class Seguradora:
    nome: str = ""  # nome que aparece na coluna SEGURADORA

    def baixar(self, page) -> Path:  # pragma: no cover - depende do site
        raise NotImplementedError

    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        raise NotImplementedError


# ---------------------------------------------------------------- utilidades


def chave(texto: str) -> str:
    """'Prêmio Líquido' -> 'PREMIO_LIQUIDO' (sem acento, maiúsculo)."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "_", t.upper()).strip("_")


def ler_tabela(arquivo: Path, cabecalho_com: tuple[str, ...] = ()) -> pd.DataFrame:
    """Lê CSV (qualquer separador/codificação) ou Excel, tudo como texto.

    `cabecalho_com`: nomes de coluna que identificam a linha de cabeçalho, para
    relatórios que trazem linhas de resumo antes da tabela (ex.: Tokio Marine).
    """
    arquivo = Path(arquivo)
    if arquivo.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
        if cabecalho_com:
            bruto = pd.read_excel(arquivo, dtype=str, header=None)
            alvo = {chave(c) for c in cabecalho_com}
            for i in range(min(len(bruto), 40)):
                if alvo & {chave(v) for v in bruto.iloc[i].dropna()}:
                    df = bruto.iloc[i + 1:].copy()
                    df.columns = [texto(v) or f"UNNAMED_{j}" for j, v in enumerate(bruto.iloc[i])]
                    break
            else:
                raise ValueError(f"Cabeçalho com {cabecalho_com} não encontrado em {arquivo.name}")
        else:
            df = pd.read_excel(arquivo, dtype=str)
    else:
        bruto = arquivo.read_bytes()
        try:
            conteudo = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            conteudo = bruto.decode("latin-1")
        linhas = conteudo.splitlines()
        while linhas and not linhas[0].strip():  # ignora linhas em branco no topo
            linhas.pop(0)
        cabecalho = linhas[0] if linhas else ""
        sep = max((";", ",", "\t", "|"), key=cabecalho.count)
        with warnings.catch_warnings():  # linhas com ";" sobrando no fim
            warnings.simplefilter("ignore")
            df = pd.read_csv(io.StringIO("\n".join(linhas)), sep=sep, dtype=str,
                             keep_default_na=False, index_col=False)
        # Excel-CSV usa ="123" para preservar zeros à esquerda (ex.: CPF)
        df = df.apply(lambda col: col.astype(str).str.replace(r'^="?(.*?)"?$', r"\1", regex=True))
    df.columns = [chave(c) for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c and not c.startswith("UNNAMED")]]
    return df.replace("", pd.NA).dropna(how="all")


def achar_coluna(df: pd.DataFrame, *candidatos: str) -> str | None:
    """Procura a 1ª coluna cujo nome começa com algum dos candidatos."""
    for cand in candidatos:
        cand = chave(cand)
        for col in df.columns:
            if col == cand:
                return col
        for col in df.columns:
            if col.startswith(cand):
                return col
    return None


def para_numero(valor) -> float | None:
    """'2.341,57' / '2341,57' / '2341.57' -> 2341.57"""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    s = re.sub(r"[^\d,.\-]", "", str(valor))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def para_data(valor):
    """'17/11/2026' -> date(2026, 11, 17). Retorna None se vazio/inválido."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    d = pd.to_datetime(str(valor).strip(), dayfirst=True, errors="coerce")
    return None if pd.isna(d) else d.date()


def texto(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor is pd.NA:
        return ""
    s = str(valor).strip()
    if s.lower() in ("nan", "<na>", "none"):
        return ""
    # Excel às vezes grava números de apólice como 318320260538502.0
    return re.sub(r"^(\d+)\.0$", r"\1", s)


def montar_padrao(nome_seguradora: str, linhas: list[dict]) -> pd.DataFrame:
    """Recebe dicionários parciais e devolve DataFrame com COLUNAS na ordem."""
    hoje = date.today()
    df = pd.DataFrame(linhas)
    for col in COLUNAS:
        if col not in df.columns:
            df[col] = ""
    # Um portal pode trazer mais de uma seguradora (ex.: Yelum e Aliro):
    # nesse caso o módulo informa SEGURADORA linha a linha.
    df["SEGURADORA"] = [texto(v) or nome_seguradora for v in df["SEGURADORA"]]
    df["DIAS EM ATRASO"] = [
        (hoje - v).days if isinstance(v, date) else None for v in df["VENCIMENTO"]
    ]
    return df[COLUNAS]


def forma_pagamento(valor) -> str:
    """Padroniza a forma de pagamento para a lista do modelo (CARTÃO/DÉBITO/PIX/BOLETO)."""
    t = chave(texto(valor))
    if not t:
        return ""
    if "CART" in t or "CREDITO" in t:
        return "CARTÃO"
    if "DEBITO" in t or "CONTA" in t:
        return "DÉBITO"
    if "PIX" in t:
        return "PIX"
    if "BOLETO" in t or "FICHA" in t or "CARNE" in t:
        return "BOLETO"
    return texto(valor).upper()
