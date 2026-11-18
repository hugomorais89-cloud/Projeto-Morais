"""Gera a planilha Excel consolidada com todas as seguradoras."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .seguradoras.base import COLUNAS

AZUL = PatternFill("solid", fgColor="1F3864")
CINZA = PatternFill("solid", fgColor="F2F2F2")
BRANCO_NEGRITO = Font(bold=True, color="FFFFFF")


def gerar_planilha(dados: list[pd.DataFrame], status: list[dict], destino: Path) -> Path:
    if dados:
        base = pd.concat(dados, ignore_index=True)
        base = base.sort_values(["VENCIMENTO", "SEGURADORA", "SEGURADO"], na_position="last")
    else:
        base = pd.DataFrame(columns=COLUNAS)

    # Resumo por seguradora
    linhas = []
    for s in status:
        parte = base[base["SEGURADORA"] == s["seguradora"]]
        linhas.append({
            "SEGURADORA": s["seguradora"],
            "SITUAÇÃO DA EXTRAÇÃO": s["situacao"],
            "PARCELAS EM ABERTO": len(parte),
            "VALOR TOTAL": round(pd.to_numeric(parte["VALOR"], errors="coerce").sum(), 2),
            "DETALHE": s.get("detalhe", ""),
        })
    resumo = pd.DataFrame(linhas, columns=[
        "SEGURADORA", "SITUAÇÃO DA EXTRAÇÃO", "PARCELAS EM ABERTO", "VALOR TOTAL", "DETALHE"
    ])

    with pd.ExcelWriter(destino, engine="openpyxl") as xw:
        base.to_excel(xw, sheet_name="Inadimplência Consolidada", index=False)
        resumo.to_excel(xw, sheet_name="Resumo", index=False, startrow=2)

        ws = xw.sheets["Inadimplência Consolidada"]
        _formatar(ws, base, larguras={"SEGURADO": 40, "RAMO": 22})
        for col_nome in ("VENCIMENTO", "PREV. CANCELAMENTO"):
            _formato_coluna(ws, base, col_nome, "DD/MM/YYYY")
        for col_nome in ("VALOR", "COMISSÃO"):
            _formato_coluna(ws, base, col_nome, '"R$" #,##0.00')

        wr = xw.sheets["Resumo"]
        wr["A1"] = f"Extração em {datetime.now():%d/%m/%Y %H:%M}"
        wr["A1"].font = Font(bold=True, size=13)
        _formatar(wr, resumo, linha_cab=3, larguras={"DETALHE": 60})
        _formato_coluna(wr, resumo, "VALOR TOTAL", '"R$" #,##0.00', linha_cab=3)
        xw.book.move_sheet("Resumo", offset=-1)
        xw.book.active = 0

    return destino


def _formatar(ws, df, linha_cab: int = 1, larguras: dict | None = None) -> None:
    larguras = larguras or {}
    for i, nome in enumerate(df.columns, start=1):
        cel = ws.cell(row=linha_cab, column=i)
        cel.fill, cel.font = AZUL, BRANCO_NEGRITO
        cel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = larguras.get(nome, max(12, len(nome) + 4))
    ws.freeze_panes = ws.cell(row=linha_cab + 1, column=1)
    if len(df):
        ws.auto_filter.ref = (
            f"A{linha_cab}:{get_column_letter(len(df.columns))}{linha_cab + len(df)}"
        )
    for r in range(linha_cab + 1, linha_cab + 1 + len(df)):
        if (r - linha_cab) % 2 == 0:
            for c in range(1, len(df.columns) + 1):
                ws.cell(row=r, column=c).fill = CINZA


def _formato_coluna(ws, df, nome: str, formato: str, linha_cab: int = 1) -> None:
    if nome not in df.columns:
        return
    c = list(df.columns).index(nome) + 1
    for r in range(linha_cab + 1, linha_cab + 1 + len(df)):
        ws.cell(row=r, column=c).number_format = formato
