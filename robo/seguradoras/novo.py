"""Novo Seguros — Portal do Corretor.

Caminho no portal (conforme vídeo da equipe):
  login (e-mail e senha) > botão vermelho "Vencidos" no topo
  (abre Buscar Renovações já filtrado: /renovacao/buscar?vencimento=vencimento)
  > botão laranja "Exportar para Excel" > período de lançamento De/Até
  (o portal aceita no máximo 15 dias) > Exportar (XLSX)

A planilha respeita os filtros da tela (só os vencidos). Colunas: Proposta, Segurado,
  CPF/CNPJ, Placa, Chassi, Modelo, Lançamento, Validade, Renovação, Situação, Cobertura,
  Prêmio, Vencimento da cobrança, Pagamento, Consultor.
VENCIMENTO = vencimento da cobrança; DATA LIMITE = validade da proposta.

Testado no portal real em 27/11/2026.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from ..navegador import achar, esperar_carregar
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
URL = "https://portaldocorretor.novoseguros.com.br/inicio/novo"
URL_VENCIDOS = "https://portaldocorretor.novoseguros.com.br/renovacao/buscar?vencimento=vencimento"
LIMITE = 120_000
PERIODO_DIAS = 15  # limite do portal na exportação por período de lançamento


class Novo(Seguradora):
    nome = "NOVO"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("NOVO")
        log.info("Login no Portal do Corretor Novo")
        page.goto(URL, wait_until="load")
        esperar_carregar(page, 2000)
        campo = page.locator("#usuario")
        campo.wait_for(state="visible", timeout=60_000)
        campo.click()
        campo.press_sequentially(usuario, delay=40)
        campo_senha = page.locator("#senha")
        campo_senha.click()
        campo_senha.press_sequentially(senha, delay=40)
        page.get_by_role("button", name="Entrar", exact=True).click()
        try:
            page.wait_for_url(lambda u: "/autenticacao" not in u, timeout=LIMITE)
        except Exception:
            raise RuntimeError("Login na Novo falhou — verifique NOVO_USUARIO/SENHA no .env")
        esperar_carregar(page, 2000)

        log.info("Vencidos (Buscar Renovações)")
        botao = achar(page, lambda f: f.get_by_role("button", name=re.compile(r"Vencid", re.I))
                      .or_(f.get_by_role("link", name=re.compile(r"Vencid", re.I))),
                      tempo=30, obrigatorio=False)
        if botao is not None:
            botao.click()
        else:
            page.goto(URL_VENCIDOS, wait_until="domcontentloaded")
        page.wait_for_url(re.compile(r"/renovacao/buscar"), timeout=LIMITE)
        esperar_carregar(page, 3000)
        rodape = achar(page, lambda f: f.get_by_text(re.compile(r"Exibindo|Nenhum", re.I)), tempo=60)
        m = re.search(r"de\s+(\d+)\s+registro", rodape.inner_text())
        na_tela = int(m.group(1)) if m else 0
        log.info("Novo: %d vencido(s) na tela", na_tela)

        hoje = date.today()
        inicio = hoje - timedelta(days=PERIODO_DIAS)
        log.info("Exportar: lançamento de %s a %s", f"{inicio:%d/%m/%Y}", f"{hoje:%d/%m/%Y}")
        page.get_by_role("button", name=re.compile("Exportar para Excel", re.I)).click()
        datas = page.locator("input[type=date]").filter(visible=True)
        datas.first.wait_for(timeout=30_000)
        datas.nth(0).fill(inicio.isoformat())
        datas.nth(1).fill(hoje.isoformat())
        page.wait_for_timeout(500)
        with page.expect_download(timeout=LIMITE) as info:
            page.get_by_role("button", name=re.compile(r"^\s*Exportar\s*$")).click()
        download = info.value
        extensao = Path(download.suggested_filename).suffix or ".xlsx"
        destino = config.PASTA_DOWNLOADS / f"novo_{hoje:%Y-%m-%d}{extensao}"
        download.save_as(destino)
        exportados = len(ler_tabela(destino))
        if exportados < na_tela:
            # a exportação só pega propostas lançadas nos últimos 15 dias
            log.warning("Novo: a tela mostra %d vencidos, mas a planilha exportada trouxe %d "
                        "(lançados há mais de %d dias ficam de fora)", na_tela, exportados, PERIODO_DIAS)
        return destino

    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        df = ler_tabela(arquivo)
        log.info("Novo — colunas do arquivo: %s", list(df.columns))
        c = {
            "proposta": achar_coluna(df, "PROPOSTA", "APOLICE"),
            "segurado": achar_coluna(df, "SEGURADO"),
            "cpf": achar_coluna(df, "CPF_CNPJ", "CPF"),
            "placa": achar_coluna(df, "PLACA"),
            "modelo": achar_coluna(df, "MODELO"),
            "validade": achar_coluna(df, "VALIDADE"),
            "situacao": achar_coluna(df, "SITUACAO"),
            "premio": achar_coluna(df, "PREMIO", "VALOR"),
            "vencimento": achar_coluna(df, "VENCIMENTO_DA_COBRANCA", "VENCIMENTO"),
            "pagamento": achar_coluna(df, "PAGAMENTO"),
        }
        if not c["vencimento"] or not (c["segurado"] or c["proposta"]):
            raise ValueError(f"Layout do relatório Novo não reconhecido. Colunas: {list(df.columns)}")

        def v(l, k):
            return l[c[k]] if c[k] else None

        linhas = []
        for _, l in df.iterrows():
            if not (texto(v(l, "segurado")) or texto(v(l, "proposta"))):
                continue
            modelo, placa = texto(v(l, "modelo")), texto(v(l, "placa"))
            linhas.append({
                "SEGURADO": texto(v(l, "segurado")),
                "CPF/CNPJ": re.sub(r"\D", "", texto(v(l, "cpf"))),
                "APÓLICE": texto(v(l, "proposta")),
                "RAMO": "AUTO" + (f" — {modelo}" if modelo else "") + (f" ({placa})" if placa else ""),
                "PARCELA": "1",
                "VENCIMENTO": para_data(v(l, "vencimento")),
                "VALOR": para_numero(v(l, "premio")),
                "PAGAMENTO": forma_pagamento(v(l, "pagamento")),
                "DATA LIMITE": para_data(v(l, "validade")),
                "SITUAÇÃO": texto(v(l, "situacao")),
            })
        return montar_padrao(self.nome, linhas)
