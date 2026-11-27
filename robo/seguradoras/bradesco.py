"""Bradesco Seguros — Portal de Negócios.

Caminho no portal (conforme vídeo da equipe):
  login (1ª tela: CPF/CNPJ > Continuar; 2ª tela: login e senha > Entrar)
  > aba AUTO > card "Parcelas em Atraso" > Ver detalhes > Relatórios > Solicitar relatório
  > Período de vencimento "30 dias", formato .XLS, frequência "Somente hoje" > Solicitar relatório
  > na lista, quando o relatório do dia fica "Finalizado" > Baixar

Credenciais no .env: BRADESCO_CPF_CNPJ (1ª tela), BRADESCO_USUARIO e BRADESCO_SENHA (2ª tela).

Testado no portal real em 27/11/2026:
  - aviso de cookies: o robô recusa os não necessários;
  - ao abrir AUTO podem aparecer "Sua senha expira em breve" (clica "Mais tarde")
    e um banner de propaganda (fecha no X).
"""
from __future__ import annotations

import logging
import os
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
URL = "https://wwwn.bradescoseguros.com.br/pnegocios2/wps/portal/portaldenegociosnovo"
LIMITE = 120_000
ESPERA_RELATORIO = 600  # segundos aguardando o relatório sair de "Em fila"/"Processando"


class Bradesco(Seguradora):
    nome = "BRADESCO"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("BRADESCO")
        cpf_cnpj = os.getenv("BRADESCO_CPF_CNPJ", "").strip()
        if not cpf_cnpj:
            raise RuntimeError("Preencha BRADESCO_CPF_CNPJ no arquivo .env")

        log.info("Login no Portal de Negócios Bradesco")
        page.goto(URL, wait_until="load")
        esperar_carregar(page, 3000)
        recusar = page.locator("#adopt-reject-all-button")
        if recusar.count() and recusar.is_visible():
            log.info("Cookies: recusando os não necessários")
            recusar.click()
            page.wait_for_timeout(1000)
        campo = page.locator("#CpfCnpjTelaInicial")
        campo.click()
        campo.press_sequentially(cpf_cnpj, delay=60)
        page.locator("#tag_Home_Login-Continuar").click()

        campo_usuario = page.locator("#input_cpf_cnpj")
        try:
            campo_usuario.wait_for(state="visible", timeout=60_000)
        except Exception:
            raise RuntimeError("Bradesco: CPF/CNPJ da 1ª tela recusado — confira BRADESCO_CPF_CNPJ no .env")
        campo_usuario.click()
        campo_usuario.press_sequentially(usuario, delay=60)
        campo_senha = page.locator("#input_senha")
        campo_senha.click()
        campo_senha.press_sequentially(senha, delay=60)
        page.locator("#loginButton2").click()
        try:
            page.wait_for_url(re.compile(r"/arealogada/"), timeout=LIMITE)
        except Exception:
            raise RuntimeError("Login no Bradesco falhou — verifique BRADESCO_USUARIO/SENHA no .env")
        esperar_carregar(page, 3000)

        log.info("AUTO > Parcelas em Atraso > Relatórios")
        achar(page, lambda f: f.locator("a").filter(has_text=re.compile(r"^\s*AUTO\s*$"))).click()
        page.wait_for_timeout(5000)
        esperar_carregar(page, 2000)
        self._fechar_avisos(page)

        titulo = achar(page, lambda f: f.get_by_text(re.compile(r"^\s*Parcelas em Atraso\s*$", re.I)),
                       tempo=60)
        caixa = titulo.locator("xpath=ancestor::*[.//*[normalize-space()='Ver detalhes']][1]")
        caixa.get_by_text("Ver detalhes", exact=True).first.click()
        page.wait_for_timeout(3000)
        esperar_carregar(page, 2000)
        achar(page, lambda f: f.get_by_role("button", name=re.compile(r"Relat[óo]rios", re.I)),
              tempo=60).click()
        page.wait_for_timeout(4000)
        esperar_carregar(page, 2000)

        log.info("Solicitando relatório: 30 dias, XLS, somente hoje")
        achar(page, lambda f: f.get_by_role("button", name=re.compile(r"Solicitar relat", re.I)),
              tempo=60).click()
        page.wait_for_timeout(3000)
        esperar_carregar(page, 1000)
        page.get_by_role("button", name=re.compile(r"^\s*30 dias\s*$")).click()
        page.get_by_text(re.compile(r"^\s*\.XLS\s*$")).first.click()
        page.get_by_role("button", name=re.compile(r"^\s*Somente hoje\s*$")).click()
        page.wait_for_timeout(500)
        page.get_by_role("button", name=re.compile(r"^\s*Solicitar relat")).last.click()
        page.wait_for_timeout(5000)
        esperar_carregar(page, 2000)

        linha = self._esperar_relatorio(page)
        botao = linha.locator("button:has(i.icon-nav-baixar)")
        with page.expect_download(timeout=LIMITE) as info:
            botao.click()
        download = info.value
        extensao = Path(download.suggested_filename).suffix or ".xls"
        destino = config.PASTA_DOWNLOADS / f"bradesco_{date.today():%Y-%m-%d}{extensao}"
        download.save_as(destino)
        return destino

    @staticmethod
    def _fechar_avisos(page) -> None:
        mais_tarde = achar(page, lambda f: f.get_by_role("button", name=re.compile(r"Mais tarde", re.I)),
                           tempo=8, obrigatorio=False)
        if mais_tarde is not None:
            log.warning("Bradesco: o portal avisa que a senha expira em breve (clicado 'Mais tarde')")
            mais_tarde.click()
            page.wait_for_timeout(1500)
        fechar = page.locator("button.close[aria-label=Close]")
        for i in range(fechar.count()):
            if fechar.nth(i).is_visible():
                fechar.nth(i).click()
                page.wait_for_timeout(1000)

    @staticmethod
    def _esperar_relatorio(page):
        """Espera o relatório de hoje (XLS) mais recente da lista ficar 'Finalizado'."""
        hoje = f"{date.today():%d/%m/%Y}"
        fim = time.monotonic() + ESPERA_RELATORIO
        while True:
            linha = page.locator("table tbody tr").filter(has_text="XLS").filter(has_text=hoje).first
            conteudo = linha.inner_text() if linha.count() else ""
            if "Finalizado" in conteudo:
                return linha
            if re.search(r"\bErro\b", conteudo):
                raise RuntimeError("Bradesco: o portal marcou o relatório como 'Erro'")
            if time.monotonic() > fim:
                raise RuntimeError(f"Bradesco: relatório não ficou pronto em {ESPERA_RELATORIO // 60} min "
                                   f"(situação: {conteudo.strip()[:80]!r})")
            log.info("Bradesco: aguardando o relatório (%s)", " ".join(conteudo.split())[-30:] or "na fila")
            page.wait_for_timeout(15_000)
            page.reload(wait_until="domcontentloaded")
            esperar_carregar(page, 3000)

    # ---------------------------------------------------------- conversão
    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        df = ler_tabela(arquivo, cabecalho_com=("Nome do segurado",))
        log.info("Bradesco — colunas do arquivo: %s", list(df.columns))
        c = {
            "segurado": achar_coluna(df, "NOME_DO_SEGURADO", "NOME"),
            "cpf": achar_coluna(df, "CPF_CNPJ", "CPF"),
            "apolice": achar_coluna(df, "SUC_AG_APOL_END", "APOLICE"),
            "modalidade": achar_coluna(df, "MODALIDADE"),
            "parcela": achar_coluna(df, "PARCELA"),
            "valor": achar_coluna(df, "VALOR"),
            "vencimento": achar_coluna(df, "VENCIMENTO"),
            "limite": achar_coluna(df, "DATA_LIMITE"),
            "forma": achar_coluna(df, "FORMA_DE_PAGAMENTO", "FORMA"),
            "celular": achar_coluna(df, "TELEFONE_CELULAR"),
            "fixo": achar_coluna(df, "TELEFONE_FIXO"),
            "obs": achar_coluna(df, "OBSERVACOES", "OBS"),
        }
        if not c["vencimento"] or not (c["segurado"] or c["apolice"]):
            raise ValueError(f"Layout do relatório Bradesco não reconhecido. Colunas: {list(df.columns)}")

        def v(l, k):
            return l[c[k]] if c[k] else None

        linhas = []
        for _, l in df.iterrows():
            if not (texto(v(l, "segurado")) or texto(v(l, "apolice"))):
                continue
            modalidade = texto(v(l, "modalidade"))
            linhas.append({
                "SEGURADO": texto(v(l, "segurado")),
                "CPF/CNPJ": re.sub(r"\D", "", texto(v(l, "cpf"))),
                "APÓLICE": texto(v(l, "apolice")),
                "RAMO": f"AUTO ({modalidade})" if modalidade else "AUTO",
                "PARCELA": texto(v(l, "parcela")),
                "VENCIMENTO": para_data(v(l, "vencimento")),
                "VALOR": para_numero(v(l, "valor")),
                "PAGAMENTO": forma_pagamento(v(l, "forma")),
                "DATA LIMITE": para_data(v(l, "limite")),
                "TELEFONE": texto(v(l, "celular")) or texto(v(l, "fixo")),
                "SITUAÇÃO": texto(v(l, "obs")) or "Em atraso",
            })
        return montar_padrao(self.nome, linhas)
