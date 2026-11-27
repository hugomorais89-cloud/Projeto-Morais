"""Zurich — Espaço Parceiros (Portal Corretor).

Caminho no portal (conforme vídeo da equipe):
  espacoparceiros.zurich.com.br > login > Parcelas vencidas (/ParcelaVencidaCorretor)
  > período de vencimento: últimos 30 dias até hoje > Buscar > Exportar XLS

Colunas da tela/arquivo: Apólice/Endosso, Ramo, Segurado, Situação, Nº Parcela,
  Valor da Parcela, Vencimento, Tipo (forma de pagamento), O.B.S.
O "Exportar XLS" gera na verdade uma tabela HTML com extensão .xls (lida por
  base.ler_tabela): Número Apólice, Número Endosso, Número Parcela, Data Vencimento,
  Dias Atraso, Valor Parcela, Nome Segurado, Ramo, Descrição Ramo, Situação Parcela,
  Tipo de Pagamento.
A lista também traz parcelas já pagas (Situação "Pago" / "Aprovado"): são descartadas.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from ..navegador import achar, esperar_carregar, login_generico
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
URL = "https://espacoparceiros.zurich.com.br/"
URL_VENCIDAS = URL + "ParcelaVencidaCorretor"
LIMITE = 120_000
PERIODO_DIAS = 30


class Zurich(Seguradora):
    nome = "ZURICH"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("ZURICH")
        log.info("Login no Espaço Parceiros Zurich")
        page.goto(URL, wait_until="domcontentloaded")
        login_generico(page, usuario, senha)
        try:
            achar(page, lambda f: f.get_by_text(re.compile(r"Portal Corretor|Minha Conta", re.I)),
                  tempo=LIMITE / 1000)
        except Exception:
            raise RuntimeError("Login na Zurich falhou — verifique usuário/senha no .env")
        esperar_carregar(page, 2000)

        log.info("Abrindo Parcelas vencidas")
        page.goto(URL_VENCIDAS, wait_until="domcontentloaded")
        esperar_carregar(page, 3000)

        hoje = date.today()
        inicio = hoje - timedelta(days=PERIODO_DIAS)
        log.info("Período de vencimento: %s a %s", f"{inicio:%d/%m/%Y}", f"{hoje:%d/%m/%Y}")
        # Campos com datepicker jQuery UI (#inputI / #inputF): usa a API do próprio
        # datepicker; se não houver jQuery, digita só os números (com máscara) e sai com Tab
        achar(page, lambda f: f.locator("#inputI.hasDatepicker"), tempo=90)
        for seletor, valor in (("#inputI", inicio), ("#inputF", hoje)):
            texto_data = f"{valor:%d/%m/%Y}"
            campo = page.locator(seletor)
            ok = page.evaluate("""([s, d]) => { const $ = window.jQuery; if (!$) return false;
                $(s).datepicker('setDate', d).trigger('change'); $(s).datepicker('hide');
                return $(s).val() === d; }""", [seletor, texto_data])
            if not ok:
                campo.click()
                campo.press_sequentially(f"{valor:%d%m%Y}", delay=60)
                campo.press("Tab")
            page.wait_for_timeout(500)
            if campo.input_value() != texto_data:
                raise RuntimeError(f"Zurich: data {texto_data} não ficou em {seletor} "
                                   f"({campo.input_value()!r})")

        # O 1º "Buscar" da página é o do bloco "Parcelas vencidas". O portal às vezes fica
        # processando e mostra "Nenhum resultado" sem buscar de fato: tenta até 3 vezes.
        rotulo_buscar = re.compile(r"^\s*buscar\s*$", re.I)
        rotulo_export = re.compile(r"Exportar XLS", re.I)
        botao = None
        for tentativa in range(1, 4):
            achar(page, lambda f: f.get_by_role("button", name=rotulo_buscar)).click()
            botao = achar(page, lambda f: f.get_by_role("button", name=rotulo_export)
                          .or_(f.get_by_text(rotulo_export)), tempo=150, obrigatorio=False)
            if botao is not None:
                break
            log.warning("Zurich: busca sem resultado (tentativa %d de 3) — repetindo", tentativa)
            esperar_carregar(page, 5000)
        if botao is None:
            raise RuntimeError("Zurich: a busca não trouxe resultados após 3 tentativas")
        page.wait_for_timeout(2000)
        # ExportaExcel gera o arquivo no navegador: não esperar navegação após o clique
        with page.expect_download(timeout=LIMITE) as info:
            botao.click(no_wait_after=True)
        download = info.value
        extensao = Path(download.suggested_filename).suffix or ".xls"
        destino = config.PASTA_DOWNLOADS / f"zurich_{hoje:%Y-%m-%d}{extensao}"
        download.save_as(destino)
        return destino

    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        df = ler_tabela(arquivo, cabecalho_com=("Nome Segurado", "Segurado", "Número Apólice"))
        log.info("Zurich — colunas do arquivo: %s", list(df.columns))
        c = {
            "apolice": achar_coluna(df, "NUMERO_APOLICE", "APOLICE"),
            "ramo": achar_coluna(df, "DESCRICAO_RAMO", "RAMO"),
            "segurado": achar_coluna(df, "NOME_SEGURADO", "SEGURADO", "NOME"),
            "cpf": achar_coluna(df, "CPF", "CNPJ"),
            "situacao": achar_coluna(df, "SITUACAO", "STATUS"),
            "parcela": achar_coluna(df, "NUMERO_PARCELA", "N_PARCELA", "PARCELA"),
            "valor": achar_coluna(df, "VALOR"),
            "vencimento": achar_coluna(df, "DATA_VENCIMENTO", "VENCIMENTO"),
            "tipo": achar_coluna(df, "TIPO_DE_PAGAMENTO", "TIPO", "FORMA"),
            "obs": achar_coluna(df, "O_B_S", "OBS"),
            "telefone": achar_coluna(df, "TELEFONE", "CELULAR"),
        }
        if not c["vencimento"] or not (c["segurado"] or c["apolice"]):
            raise ValueError(f"Layout do relatório Zurich não reconhecido. Colunas: {list(df.columns)}")

        def v(l, k):
            return l[c[k]] if c[k] else None

        linhas = []
        for _, l in df.iterrows():
            if not (texto(v(l, "segurado")) or texto(v(l, "apolice"))):
                continue
            situacao = texto(v(l, "situacao"))
            if re.search(r"\bpag[oa]\b|aprovad", situacao, re.I):
                continue  # já quitada (Pago) ou pagamento aprovado
            obs = texto(v(l, "obs"))
            linhas.append({
                "SEGURADO": texto(v(l, "segurado")),
                "CPF/CNPJ": re.sub(r"\D", "", texto(v(l, "cpf"))),
                "APÓLICE": texto(v(l, "apolice")),
                "RAMO": texto(v(l, "ramo")),
                "PARCELA": texto(v(l, "parcela")),
                "VENCIMENTO": para_data(v(l, "vencimento")),
                "VALOR": para_numero(v(l, "valor")),
                "TELEFONE": texto(v(l, "telefone")),
                "PAGAMENTO": forma_pagamento(v(l, "tipo")),
                "SITUAÇÃO": f"{situacao} — {obs}" if obs else situacao,
            })
        return montar_padrao(self.nome, linhas)
