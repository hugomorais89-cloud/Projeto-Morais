"""Allianz — portal AllianzNet.

Caminho no portal (conforme vídeo da equipe):
  Gestão > Financeiro > Gestão de Parcelas > aba "Gestão de Inadimplentes"
  Status = Inadimplente | Vencimento de <início> até <hoje>
  Pesquisar > Gerar Planilha  (baixa um CSV)

Colunas do CSV da Allianz:
  RECIBO, PARCELA, VENCIMENTO, CPF_CNPJ, NOME_DO_SEGURADO, RAMO,
  DT_FIM_VIGENCIA, DT_PREV_CANCELAMENTO, PREMIO, COMISSAO
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from ..navegador import achar, achar_todos, clicar_texto, esperar_carregar
from .base import (
    Seguradora,
    achar_coluna,
    ler_tabela,
    montar_padrao,
    para_data,
    para_numero,
    texto,
)

URL_HOME = "https://www.allianznet.com.br/ngx-azb-epac/private/home"


class Allianz(Seguradora):
    nome = "ALLIANZ"

    # ------------------------------------------------------------ navegação
    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("ALLIANZ")

        page.goto(URL_HOME, wait_until="domcontentloaded")
        esperar_carregar(page)
        self._login_se_necessario(page, usuario, senha)

        # Menu: Gestão > Financeiro > Gestão de Parcelas
        clicar_texto(page, "Gestão", exato=True)
        clicar_texto(page, "Financeiro")
        clicar_texto(page, "Gestão de Parcelas")
        esperar_carregar(page)

        # Aba "Gestão de Inadimplentes"
        clicar_texto(page, "Gestão de Inadimplentes")
        esperar_carregar(page)

        self._preencher_filtro(page)

        clicar_texto(page, "Pesquisar", exato=True, papel="button")
        esperar_carregar(page, extra_ms=3000)

        botao = achar(page, lambda f: f.get_by_text("Gerar Planilha"), tempo=60)
        with page.expect_download(timeout=120_000) as info:
            botao.click()
        download = info.value
        destino = config.PASTA_DOWNLOADS / (
            f"allianz_{date.today():%Y-%m-%d}{Path(download.suggested_filename).suffix or '.csv'}"
        )
        download.save_as(destino)
        return destino

    def _login_se_necessario(self, page, usuario: str, senha: str) -> None:
        campo_senha = page.locator("input[type=password]")
        try:
            campo_senha.first.wait_for(state="visible", timeout=15_000)
        except Exception:
            return  # já está logado (sessão ativa)

        # O campo de usuário é o input de texto visível antes da senha
        campo_usuario = page.locator(
            "input[type=text]:visible, input[type=email]:visible, "
            "input:not([type]):visible"
        ).first
        campo_usuario.fill(usuario)
        campo_senha.first.fill(senha)

        botao = page.get_by_role(
            "button", name=re.compile(r"entrar|acessar|login|continuar", re.I)
        )
        if botao.count():
            botao.first.click()
        else:
            campo_senha.first.press("Enter")

        page.wait_for_url(re.compile(r"/private/"), timeout=60_000)
        esperar_carregar(page)

    def _preencher_filtro(self, page) -> None:
        hoje = date.today()
        inicio = hoje - timedelta(days=config.DIAS_RETROATIVOS)

        # Status = Inadimplente (pode ser <select> ou lista personalizada)
        status = achar(
            page, lambda f: f.locator("select").filter(has_text="Inadimplente"), tempo=5,
            obrigatorio=False,
        )
        if status is not None:
            status.select_option(label="Inadimplente")
        else:
            try:
                rotulo = achar(page, lambda f: f.get_by_text("Status", exact=True), tempo=5)
                rotulo.locator("xpath=following::*[self::select or @role='combobox' or contains(@class,'select')][1]").click()
                clicar_texto(page, "Inadimplente", exato=True)
            except Exception:
                pass  # em geral já vem "Inadimplente" selecionado

        # Datas de vencimento (dois campos dd/mm/aaaa: "Vencimento" e "Até")
        datas = achar_todos(
            page,
            lambda f: f.locator(
                "input[placeholder*='dd/mm' i]:visible, input[placeholder*='aaaa' i]:visible"
            ),
            tempo=20,
        )
        for campo, valor in ((datas.nth(0), inicio), (datas.nth(1), hoje)):
            campo.click()
            campo.fill("")
            campo.type(f"{valor:%d/%m/%Y}", delay=60)
            campo.press("Tab")

    # ---------------------------------------------------------- conversão
    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        df = ler_tabela(arquivo)
        c = {
            "segurado": achar_coluna(df, "NOME"),
            "cpf": achar_coluna(df, "CPF", "CNPJ"),
            "apolice": achar_coluna(df, "APOLICE"),
            "recibo": achar_coluna(df, "RECIBO"),
            "ramo": achar_coluna(df, "RAMO"),
            "parcela": achar_coluna(df, "PARCELA", "PARC"),
            "vencimento": achar_coluna(df, "VENCIMENTO", "VENC", "DT_VENC"),
            "valor": achar_coluna(df, "PREMIO", "VALOR"),
            "cancelamento": achar_coluna(df, "DT_PREV_CANC", "PREV_CANC", "CANCEL"),
            "comissao": achar_coluna(df, "COMISSAO"),
        }
        faltando = [k for k in ("segurado", "vencimento") if not c[k]]
        if faltando:
            raise ValueError(
                f"Layout do relatório Allianz mudou — colunas não encontradas: "
                f"{faltando}. Colunas do arquivo: {list(df.columns)}"
            )

        def v(linha, k):
            return linha[c[k]] if c[k] else None

        linhas = []
        for _, l in df.iterrows():
            linhas.append(
                {
                    "SEGURADO": texto(v(l, "segurado")),
                    "CPF/CNPJ": texto(v(l, "cpf")),
                    "APÓLICE": texto(v(l, "apolice")),
                    "RECIBO": texto(v(l, "recibo")),
                    "RAMO": texto(v(l, "ramo")),
                    "PARCELA": texto(v(l, "parcela")),
                    "VENCIMENTO": para_data(v(l, "vencimento")),
                    "VALOR": para_numero(v(l, "valor")),
                    "PREV. CANCELAMENTO": para_data(v(l, "cancelamento")),
                    "COMISSÃO": para_numero(v(l, "comissao")),
                }
            )
        return montar_padrao(self.nome, linhas)
