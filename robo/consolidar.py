"""Gera a planilha Excel consolidada com todas as seguradoras."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .seguradoras.base import COLUNAS, COLUNAS_EXTRAS

AZUL = PatternFill("solid", fgColor="1F4E78")        # mesmo tom do modelo da equipe
AZUL_EXTRA = PatternFill("solid", fgColor="5B7FA6")  # colunas extras trazidas pelo robô
ROSA = PatternFill("solid", fgColor="FFC7CE", bgColor="FFC7CE")
FORMAS_PAGAMENTO = ["CARTÃO", "DÉBITO", "PIX", "BOLETO"]
# Larguras iguais às do modelo
LARGURAS = {"SEGURADORA": 15, "SEGURADO": 56, "APÓLICE": 19, "CPF/CNPJ": 17, "PAGAMENTO": 14,
            "PARCELA": 12, "VENCIMENTO": 16, "PRODUTOR": 21, "NOVA DATA": 17,
            "CONTATO": 13, "DATA LIMITE": 15, "RAMO": 10, "DIAS EM ATRASO": 11}
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
        _formatar(ws, base, larguras=LARGURAS)
        for i, nome in enumerate(base.columns, start=1):
            if nome in COLUNAS_EXTRAS:
                ws.cell(row=1, column=i).fill = AZUL_EXTRA
        ultima = max(len(base) + 1, 2) + 2000  # deixa espaço para linhas novas
        letra = lambda nome: get_column_letter(list(base.columns).index(nome) + 1)
        # Segurado repetido em rosa (mesma regra do modelo)
        b = letra("SEGURADO")
        ws.conditional_formatting.add(
            f"{b}2:{b}{ultima}",
            FormulaRule(formula=[f'AND({b}2<>"",COUNTIF(${b}$2:${b}${ultima},{b}2)>1)'],
                        fill=ROSA, font=Font(color="9C0006")),
        )
        # Lista suspensa para forma de pagamento
        dv = DataValidation(type="list", formula1='"' + ",".join(FORMAS_PAGAMENTO) + '"',
                            allow_blank=True, showErrorMessage=False)
        ws.add_data_validation(dv)
        dv.add(f"{letra('PAGAMENTO')}2:{letra('PAGAMENTO')}{ultima}")
        for col_nome in ("NOVA DATA", "CONTATO", "DATA LIMITE"):
            c = letra(col_nome)
            for r in range(2, len(base) + 2):
                ws[f"{c}{r}"].number_format = "DD/MM/YYYY"
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
