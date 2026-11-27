"""Banco de dados local (SQLite) com o histórico de todas as execuções.

Tabelas:
  execucoes  - uma linha por vez que o robô rodou
  extracoes  - uma linha por seguradora em cada execução (OK/ERRO, qtd, valor)
  parcelas   - as parcelas em aberto de cada extração bem-sucedida
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

import pandas as pd

from . import config

ARQUIVO_BANCO = config.PASTA_DADOS / "inadimplencia.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS execucoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio      TEXT NOT NULL,
    fim         TEXT,
    origem      TEXT
);
CREATE TABLE IF NOT EXISTS extracoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao_id INTEGER NOT NULL REFERENCES execucoes(id),
    data        TEXT NOT NULL,          -- AAAA-MM-DD
    horario     TEXT NOT NULL,          -- AAAA-MM-DD HH:MM:SS
    seguradora  TEXT NOT NULL,
    situacao    TEXT NOT NULL,          -- OK | ERRO
    quantidade  INTEGER DEFAULT 0,
    valor_total REAL DEFAULT 0,
    detalhe     TEXT
);
CREATE INDEX IF NOT EXISTS ix_extracoes_seg ON extracoes(seguradora, data);
CREATE TABLE IF NOT EXISTS parcelas (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    extracao_id        INTEGER NOT NULL REFERENCES extracoes(id),
    seguradora         TEXT,
    segurado           TEXT,
    cpf_cnpj           TEXT,
    apolice            TEXT,
    recibo             TEXT,
    ramo               TEXT,
    parcela            TEXT,
    vencimento         TEXT,            -- AAAA-MM-DD
    valor              REAL,
    prev_cancelamento  TEXT,            -- AAAA-MM-DD
    comissao           REAL,
    telefone           TEXT,
    pagamento          TEXT,
    situacao           TEXT
);
CREATE INDEX IF NOT EXISTS ix_parcelas_extracao ON parcelas(extracao_id);
"""


@contextmanager
def conectar():
    con = sqlite3.connect(ARQUIVO_BANCO)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(ESQUEMA)
        # bancos criados antes destas colunas existirem
        existentes = {r[1] for r in con.execute("PRAGMA table_info(parcelas)")}
        for col in ("telefone", "pagamento", "situacao"):
            if col not in existentes:
                con.execute(f"ALTER TABLE parcelas ADD COLUMN {col} TEXT")
        yield con
        con.commit()
    finally:
        con.close()


def arquivos_ok_do_dia(dia: str) -> dict[str, str]:
    """{nome_seguradora: nome do arquivo baixado} da última extração OK de cada seguradora no dia."""
    with conectar() as con:
        linhas = con.execute("""
            SELECT e.seguradora, e.detalhe FROM extracoes e
            JOIN (SELECT seguradora, MAX(id) id FROM extracoes
                  WHERE data=? AND situacao='OK' GROUP BY seguradora) u ON u.id = e.id
        """, (dia,)).fetchall()
    return {l["seguradora"]: l["detalhe"] for l in linhas if l["detalhe"]}


def _iso(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    return str(v) or None


def _num(v) -> float | None:
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def salvar_execucao(inicio: datetime, status: list[dict], dados: dict[str, pd.DataFrame],
                    origem: str = "robo") -> int:
    """Grava uma execução completa. `dados` = {nome_seguradora: DataFrame padrão}."""
    agora = datetime.now()
    with conectar() as con:
        cur = con.execute(
            "INSERT INTO execucoes (inicio, fim, origem) VALUES (?, ?, ?)",
            (inicio.isoformat(" ", "seconds"), agora.isoformat(" ", "seconds"), origem),
        )
        execucao_id = cur.lastrowid
        for s in status:
            df = dados.get(s["seguradora"])
            qtd = 0 if df is None else len(df)
            total = 0.0 if df is None else float(pd.to_numeric(df["VALOR"], errors="coerce").sum())
            cur = con.execute(
                "INSERT INTO extracoes (execucao_id, data, horario, seguradora, situacao,"
                " quantidade, valor_total, detalhe) VALUES (?,?,?,?,?,?,?,?)",
                (execucao_id, agora.strftime("%Y-%m-%d"), agora.isoformat(" ", "seconds"),
                 s["seguradora"], s["situacao"], qtd, round(total, 2), s.get("detalhe", "")),
            )
            if df is None:
                continue
            extracao_id = cur.lastrowid
            con.executemany(
                "INSERT INTO parcelas (extracao_id, seguradora, segurado, cpf_cnpj, apolice,"
                " recibo, ramo, parcela, vencimento, valor, prev_cancelamento, comissao,"
                " telefone, pagamento, situacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (extracao_id, l["SEGURADORA"], l["SEGURADO"], l["CPF/CNPJ"], l["APÓLICE"],
                     l["RECIBO"], l["RAMO"], l["PARCELA"], _iso(l["VENCIMENTO"]),
                     _num(l["VALOR"]), _iso(l["PREV. CANCELAMENTO"]), _num(l["COMISSÃO"]),
                     l["TELEFONE"] or None, l["PAGAMENTO"] or None, l["SITUAÇÃO"] or None)
                    for l in df.to_dict("records")
                ],
            )
    return execucao_id
