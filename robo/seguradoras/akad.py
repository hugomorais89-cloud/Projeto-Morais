"""Akad Seguros — Akad Digital.

Caminho no portal (conforme vídeos da equipe):
  login (CPF e senha) > tela "Proteja sua conta": "Continuar sem proteção" (orientação da equipe)
  > Controle de Parcelas > Exportar Relatório (abre /hub/relatorios)
  > Tipo de dado "Inadimplentes", Período "Todas parcelas em atraso" (formato CSV) > Gerar relatório
  > atualizar a página até o relatório novo aparecer com "Baixar" > Baixar

Testado no portal real em 27/11/2026: login, geração e download funcionam. Nesse dia não havia
inadimplentes e o CSV veio só com a linha "sep=," (sem cabeçalho) — por isso as colunas abaixo
são reconhecidas por nomes prováveis; confira na primeira vez que houver parcelas em atraso.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
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
URL_LOGIN = "https://digital.akadseguros.com.br/login"
URL_RELATORIOS = "https://digital.akadseguros.com.br/hub/relatorios"
LIMITE = 120_000
ESPERA_RELATORIO = 600  # segundos atualizando a página até o relatório ficar disponível


class Akad(Seguradora):
    nome = "AKAD"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("AKAD")
        log.info("Login no Akad Digital")
        page.goto(URL_LOGIN, wait_until="load")
        esperar_carregar(page, 2000)
        campo = page.locator("#cpf")
        campo.wait_for(state="visible", timeout=60_000)
        campo.click()
        campo.press_sequentially(usuario, delay=50)
        campo_senha = page.locator("#password")
        campo_senha.click()
        campo_senha.press_sequentially(senha, delay=50)
        recusado = []
        page.on("response", lambda r: recusado.append(r.status)
                if "connect/token" in r.url and r.status >= 400 else None)
        page.get_by_role("button", name="Entrar", exact=True).click()
        page.wait_for_timeout(4000)
        if recusado:
            raise RuntimeError("Login na AKAD falhou — verifique AKAD_USUARIO/SENHA no .env")
        sem_protecao = achar(page, lambda f: f.get_by_text(re.compile(r"continuar sem prote", re.I)),
                             tempo=30, obrigatorio=False)
        if sem_protecao is not None:
            log.info("Tela 'Proteja sua conta': Continuar sem proteção")
            sem_protecao.click()
        try:
            page.wait_for_url(lambda u: "/login" not in u, timeout=LIMITE)
        except Exception:
            raise RuntimeError("Login na AKAD não concluiu (continua na tela de login)")
        esperar_carregar(page, 3000)

        log.info("Relatórios: Inadimplentes, todas as parcelas em atraso")
        page.goto(URL_RELATORIOS, wait_until="domcontentloaded")
        esperar_carregar(page, 3000)
        tipo = page.locator("select[name='reportInfo.dataType']")
        tipo.wait_for(timeout=60_000)
        tipo.select_option(label="Inadimplentes")
        page.wait_for_timeout(1500)
        periodo = page.locator("select[name='reportInfo.period']")
        valor = periodo.evaluate(
            "s => ([...s.options].find(o => /todas/i.test(o.text)) || {}).value || null")
        if not valor:
            raise RuntimeError("AKAD: opção 'Todas parcelas em atraso' não encontrada no Período")
        periodo.select_option(valor)
        page.wait_for_timeout(1000)

        antes = self._ids_relatorios(page)
        page.get_by_role("button", name=re.compile(r"Gerar relat", re.I)).click()
        page.wait_for_timeout(3000)
        linha = self._esperar_relatorio(page, antes)
        botao = linha.locator("button.ds-button").filter(has_text="Baixar")
        with page.expect_download(timeout=LIMITE) as info:
            botao.click()
        download = info.value
        extensao = Path(download.suggested_filename).suffix or ".csv"
        destino = config.PASTA_DOWNLOADS / f"akad_{date.today():%Y-%m-%d}{extensao}"
        download.save_as(destino)
        return destino

    @staticmethod
    def _ids_relatorios(page) -> set[str]:
        return set(page.locator(".list__row[data-testid]").evaluate_all(
            "els => els.map(e => e.dataset.testid)"))

    @staticmethod
    def _esperar_relatorio(page, antes: set[str]):
        """Atualiza a página até o relatório novo aparecer com o botão 'Baixar'."""
        fim = time.monotonic() + ESPERA_RELATORIO
        while True:
            for rid in Akad._ids_relatorios(page) - antes:
                linha = page.locator(f".list__row[data-testid='{rid}']")
                if linha.locator("button.ds-button").filter(has_text="Baixar").count():
                    return linha
            if time.monotonic() > fim:
                raise RuntimeError(f"AKAD: relatório não ficou disponível em {ESPERA_RELATORIO // 60} min")
            log.info("AKAD: aguardando o relatório ficar disponível (atualizando a página)")
            page.wait_for_timeout(10_000)
            page.reload(wait_until="domcontentloaded")
            esperar_carregar(page, 3000)

    # ---------------------------------------------------------- conversão
    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        arquivo = Path(arquivo)
        bruto = arquivo.read_bytes()
        try:
            conteudo = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            conteudo = bruto.decode("latin-1")
        linhas_csv = [l for l in conteudo.splitlines() if not l.lower().startswith("sep=")]
        if not any(l.strip() for l in linhas_csv):
            log.info("AKAD: relatório sem parcelas em atraso")
            return montar_padrao(self.nome, [])
        limpo = arquivo.with_name(arquivo.stem + "_limpo.csv")
        limpo.write_text("\n".join(linhas_csv), encoding="utf-8")
        df = ler_tabela(limpo)
        log.info("AKAD — colunas do arquivo: %s", list(df.columns))
        c = {
            "segurado": achar_coluna(df, "SEGURADO", "TOMADOR", "NOME", "CLIENTE"),
            "cpf": achar_coluna(df, "CPF", "CNPJ", "DOCUMENTO"),
            "apolice": achar_coluna(df, "APOLICE", "NUMERO_APOLICE", "PROPOSTA"),
            "produto": achar_coluna(df, "PRODUTO", "RAMO"),
            "parcela": achar_coluna(df, "PARCELA", "NUMERO_PARCELA"),
            "vencimento": achar_coluna(df, "VENCIMENTO", "DATA_VENCIMENTO", "DATA_DE_VENCIMENTO"),
            "valor": achar_coluna(df, "VALOR", "PREMIO"),
            "forma": achar_coluna(df, "FORMA", "MEIO"),
            "telefone": achar_coluna(df, "TELEFONE", "CELULAR"),
            "status": achar_coluna(df, "STATUS", "SITUACAO"),
            "comissao": achar_coluna(df, "COMISSAO"),
        }
        if not c["vencimento"] or not (c["segurado"] or c["apolice"]):
            raise ValueError(f"Layout do relatório AKAD não reconhecido. Colunas: {list(df.columns)}")

        def v(l, k):
            return l[c[k]] if c[k] else None

        linhas = []
        for _, l in df.iterrows():
            if not (texto(v(l, "segurado")) or texto(v(l, "apolice"))):
                continue
            linhas.append({
                "SEGURADO": texto(v(l, "segurado")),
                "CPF/CNPJ": re.sub(r"\D", "", texto(v(l, "cpf"))),
                "APÓLICE": texto(v(l, "apolice")),
                "RAMO": texto(v(l, "produto")),
                "PARCELA": texto(v(l, "parcela")),
                "VENCIMENTO": para_data(v(l, "vencimento")),
                "VALOR": para_numero(v(l, "valor")),
                "PAGAMENTO": forma_pagamento(v(l, "forma")),
                "TELEFONE": texto(v(l, "telefone")),
                "COMISSÃO": para_numero(v(l, "comissao")),
                "SITUAÇÃO": texto(v(l, "status")) or "Inadimplente",
            })
        return montar_padrao(self.nome, linhas)
