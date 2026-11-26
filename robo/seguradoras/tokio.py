"""Tokio Marine — Portal Parceiros.

Caminho no portal (conforme vídeo da equipe):
  Login (SSO) > Corretor > selecionar corretora 32904 (H MORAIS CORRETORA DE SEGUROS LTDA-ME)
  > Financeiro > Relatórios Clientes > Clientes inadimplentes
  Ramos: "Select all" > Pesquisar > EXCEL (.xls)

O .xls traz 4 linhas de resumo antes do cabeçalho:
  Parceiro de Negócio, Corretor, Código Corretor, Segurado, Cpf/Cnpj, Negócio, Ramo,
  Apólice, Endosso, Vigência Proporcional, Telefone, Parcela, Vencimento, Valor,
  Forma Pagamento, Motivo, Repique
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import pandas as pd

from .. import config
from ..navegador import esperar_carregar
from .base import (
    Seguradora,
    achar_coluna,
    forma_pagamento,
    ler_tabela,
    montar_padrao,
    para_data,
    para_numero,
    texto,
)

log = logging.getLogger("robo")
URL_PORTAL = "https://portalparceiros.tokiomarine.com.br/"
URL_INADIMPLENTES = "https://portalparceiros.tokiomarine.com.br/portais/clientes-inadimplentes/#/"
CODIGO_CORRETORA = "32904"  # H MORAIS CORRETORA DE SEGUROS LTDA-ME
LIMITE = 120_000


class TokioMarine(Seguradora):
    nome = "TOKIO MARINE"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("TOKIO")
        log.info("Login no Portal Parceiros")
        page.goto(URL_PORTAL, wait_until="domcontentloaded")
        page.locator("#idToken1").fill(usuario)
        page.locator("#idToken2").fill(senha)
        page.locator("#loginButton_0").click()
        try:
            page.get_by_text("Corretor", exact=True).click(timeout=60_000)
        except Exception:
            raise RuntimeError("Login na Tokio Marine falhou — verifique usuário/senha no .env")

        log.info("Selecionando corretora %s", CODIGO_CORRETORA)
        linha = page.locator(f"tr:has-text('{CODIGO_CORRETORA}')").first
        try:
            linha.wait_for(timeout=60_000)
            linha.click()
        except Exception:
            # Sem janela de seleção: confere se a corretora certa já está ativa
            pass
        esperar_carregar(page, 3000)
        ativa = page.locator("#habilitaTrocaDeParceiro").inner_text(timeout=30_000)
        if CODIGO_CORRETORA not in ativa:
            raise RuntimeError(f"Corretora {CODIGO_CORRETORA} não ficou selecionada (ativa: {ativa!r})")

        log.info("Abrindo Clientes inadimplentes")
        page.goto(URL_INADIMPLENTES, wait_until="domcontentloaded")
        ramos = page.locator("input[aria-label=Ramos]")
        ramos.wait_for(timeout=LIMITE)
        page.wait_for_timeout(3000)  # a lista de ramos carrega depois do campo
        ramos.click()
        page.get_by_text("Select all", exact=True).click(timeout=LIMITE)
        page.keyboard.press("Escape")
        log.info("Ramos: %s", ramos.input_value())

        page.get_by_role("button", name="Pesquisar").click()
        botao = page.get_by_role("button", name="EXCEL")
        botao.wait_for(timeout=LIMITE)
        page.wait_for_timeout(2000)
        with page.expect_download(timeout=LIMITE) as info:
            botao.click()
        download = info.value
        extensao = Path(download.suggested_filename).suffix or ".xls"
        destino = config.PASTA_DOWNLOADS / f"tokio_{date.today():%Y-%m-%d}{extensao}"
        download.save_as(destino)
        return destino

    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        df = ler_tabela(arquivo, cabecalho_com=("Segurado",))
        c = {
            "segurado": achar_coluna(df, "SEGURADO"),
            "cpf": achar_coluna(df, "CPF"),
            "apolice": achar_coluna(df, "APOLICE"),
            "negocio": achar_coluna(df, "NEGOCIO"),
            "ramo": achar_coluna(df, "RAMO"),
            "parcela": achar_coluna(df, "PARCELA"),
            "vencimento": achar_coluna(df, "VENCIMENTO"),
            "valor": achar_coluna(df, "VALOR"),
            "telefone": achar_coluna(df, "TELEFONE"),
            "pagamento": achar_coluna(df, "FORMA_PAGAMENTO", "FORMA"),
            "motivo": achar_coluna(df, "MOTIVO"),
        }
        faltando = [k for k in ("segurado", "vencimento") if not c[k]]
        if faltando:
            raise ValueError(f"Layout do relatório Tokio mudou — faltam {faltando}. "
                             f"Colunas: {list(df.columns)}")

        def v(l, k):
            return l[c[k]] if c[k] else None

        linhas = []
        for _, l in df.iterrows():
            if not texto(v(l, "segurado")):
                continue  # linhas de total/rodapé
            ramo = texto(v(l, "ramo"))
            linhas.append({
                "SEGURADO": texto(v(l, "segurado")),
                "CPF/CNPJ": re.sub(r"\D", "", texto(v(l, "cpf"))),
                "APÓLICE": texto(v(l, "apolice")),
                "RECIBO": texto(v(l, "negocio")),
                "RAMO": ramo.split(" - ")[0] if ramo else "",
                "PARCELA": texto(v(l, "parcela")),
                "VENCIMENTO": para_data(v(l, "vencimento")),
                "VALOR": para_numero(v(l, "valor")),
                # PREV. CANCELAMENTO fica em branco: o relatório da Tokio não informa
                # (a "Vigência Proporcional" não é a data de cancelamento)
                "TELEFONE": texto(v(l, "telefone")),
                "PAGAMENTO": forma_pagamento(v(l, "pagamento")),
                "SITUAÇÃO": texto(v(l, "motivo")),
            })
        return montar_padrao(self.nome, linhas)
