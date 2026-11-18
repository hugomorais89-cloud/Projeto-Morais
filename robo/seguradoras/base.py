"""Peças comuns a todas as seguradoras.

Cada seguradora é uma classe com dois passos:
  1. baixar(page)        -> entra no portal e baixa o relatório (Excel/CSV/PDF)
  2. normalizar(arquivo) -> converte o relatório para o formato padrão (COLUNAS)
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

# Formato padrão da planilha consolidada (uma linha = uma parcela em aberto).
# As últimas colunas (PRODUTOR em diante) são de controle interno da equipe
# e saem em branco para serem preenchidas manualmente, como na planilha atual.
COLUNAS = [
    "SEGURADORA",
    "SEGURADO",
    "CPF/CNPJ",
    "APÓLICE",
    "RECIBO",
    "RAMO",
    "PARCELA",
    "VENCIMENTO",
    "DIAS EM ATRASO",
    "VALOR",
    "PREV. CANCELAMENTO",
    "COMISSÃO",
    "PRODUTOR",
    "PAGAMENTO",
    "NOVA DATA",
    "CONTATO",
    "DATA LIMITE",
]


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


def ler_tabela(arquivo: Path) -> pd.DataFrame:
    """Lê CSV (qualquer separador/codificação) ou Excel, tudo como texto."""
    arquivo = Path(arquivo)
    if arquivo.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
        df = pd.read_excel(arquivo, dtype=str)
    else:
        ultimo_erro = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                df = pd.read_csv(
                    arquivo, sep=None, engine="python", dtype=str, encoding=enc
                )
                break
            except UnicodeDecodeError as e:
                ultimo_erro = e
        else:
            raise ultimo_erro
    df.columns = [chave(c) for c in df.columns]
    return df.dropna(how="all")


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
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    s = str(valor).strip()
    return "" if s.lower() == "nan" else s


def montar_padrao(nome_seguradora: str, linhas: list[dict]) -> pd.DataFrame:
    """Recebe dicionários parciais e devolve DataFrame com COLUNAS na ordem."""
    hoje = date.today()
    df = pd.DataFrame(linhas)
    for col in COLUNAS:
        if col not in df.columns:
            df[col] = ""
    df["SEGURADORA"] = nome_seguradora
    df["DIAS EM ATRASO"] = [
        (hoje - v).days if isinstance(v, date) else None for v in df["VENCIMENTO"]
    ]
    return df[COLUNAS]
