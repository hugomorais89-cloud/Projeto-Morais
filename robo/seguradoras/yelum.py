"""Yelum Seguros (inclui ALIRO) — Novo Meu Espaço Corretor.

Caminho no portal (conforme vídeo da equipe):
  login > Financeiro > Gestão de Parcelas > aceitar "Termo de adesão" (LGPD)
  1) filtro "Atrasadas", vencimento de <90 dias atrás> até <hoje> > Buscar > Exportar Excel
  2) filtro "A Vencer", de <hoje> até <+30 dias> > Buscar > Exportar Excel
     → a equipe aproveita só as parcelas "A Vencer" com forma de pagamento PIX ou BOLETO
       cujo VENCIMENTO ORIGINAL já passou: ficaram em aberto e a seguradora reprogramou
       para PIX/boleto. VENCIMENTO = vencimento original (conta os dias em atraso) e
       DATA LIMITE = vencimento reprogramado (prazo limite para pagamento).

Colunas do Excel: Apólice, Emissão, Nome, Produto, Parcela, VencimentoAtual, Valor,
  Tipo, Status, VencimentoOriginal, IOF, MotivoRejeicao, DataRejeicao, NomeCorretora
O PRODUTO indica a seguradora: "ALIRO SEGURO AUTO..." → ALIRO; "YELUM AUTO..." → YELUM.

Testado no portal real em 26/11/2026:
  - tela de boas-vindas com o botão "Entrar no novo Meu Espaço Corretor" antes do login;
  - Gestão de Parcelas aberta direto em /lp/payment-management;
  - em "Atrasadas" as datas precisam ser menores que hoje (a busca termina ontem).
"""
from __future__ import annotations

import logging
import re
import time
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
URL = "https://novomeuespacocorretor.yelumseguros.com.br/"
URL_PARCELAS = URL + "lp/payment-management"
LIMITE = 120_000
DIAS_A_VENCER = 30


class Yelum(Seguradora):
    nome = "YELUM / ALIRO"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("YELUM")
        log.info("Login no Meu Espaço Corretor")
        page.goto(URL, wait_until="domcontentloaded")
        # Tela de boas-vindas antes do formulário de login
        entrar = achar(page, lambda f: f.get_by_role(
            "button", name=re.compile(r"Entrar no novo Meu Espa[çc]o Corretor", re.I)).or_(
            f.get_by_text(re.compile(r"Entrar no novo Meu Espa[çc]o Corretor", re.I))),
            tempo=30, obrigatorio=False)
        if entrar is not None:
            log.info("Botão 'Entrar no novo Meu Espaço Corretor'")
            entrar.click()
            esperar_carregar(page, 2000)
        login_generico(page, usuario, senha)
        try:
            page.get_by_text("Financeiro").first.wait_for(timeout=LIMITE)
        except Exception:
            raise RuntimeError("Login na Yelum falhou — verifique usuário/senha no .env")
        esperar_carregar(page, 2000)

        # Financeiro > Gestão de Parcelas é só um link para /lp/payment-management;
        # abrir direto evita o menu suspenso (que tem cópias escondidas do item)
        log.info("Abrindo Gestão de Parcelas")
        page.goto(URL_PARCELAS, wait_until="domcontentloaded")
        esperar_carregar(page, 3000)
        self._aceitar_termo(page)

        hoje = date.today()
        # Em "Atrasadas" o portal exige datas menores que hoje → termina ontem
        atrasadas = self._exportar(page, "Atrasadas", hoje - timedelta(days=config.DIAS_RETROATIVOS),
                                   hoje - timedelta(days=1), f"yelum_atrasadas_{hoje:%Y-%m-%d}.xlsx")
        try:
            self._exportar(page, "A Vencer", hoje, hoje + timedelta(days=DIAS_A_VENCER),
                           f"yelum_avencer_{hoje:%Y-%m-%d}.xlsx")
        except Exception:
            log.warning("Não foi possível exportar 'A Vencer' — seguindo só com 'Atrasadas'",
                        exc_info=True)
        return atrasadas

    @staticmethod
    def _aceitar_termo(page) -> None:
        texto_termo = achar(page, lambda f: f.get_by_text(re.compile("Declaro que li", re.I)),
                            tempo=30, obrigatorio=False)
        if texto_termo is None:
            return
        log.info("Aceitando termo de adesão (LGPD)")
        caixa = page.locator("input[type=checkbox]:visible").filter(visible=True)
        if caixa.count():
            caixa.last.check(force=True)
        else:
            texto_termo.click()
        concordo = page.get_by_role("button", name=re.compile(r"^\s*concordo\s*$", re.I))
        concordo.click(timeout=30_000)
        page.wait_for_timeout(2000)

    @staticmethod
    def _exportar(page, filtro: str, inicio: date, fim: date, nome_arquivo: str) -> Path:
        log.info("Filtro %s: %s a %s", filtro, f"{inicio:%d/%m/%Y}", f"{fim:%d/%m/%Y}")
        page.locator("select#filters").select_option(label=filtro, timeout=60_000)
        datas = page.locator("input.duet-date__input:visible, input[placeholder*='dd/mm' i]:visible")
        for i, valor in ((0, inicio), (1, fim)):
            campo = datas.nth(i)
            campo.click()
            campo.fill(f"{valor:%d/%m/%Y}")
            campo.press("Escape")
        page.get_by_role("button", name=re.compile(r"^\s*buscar\s*$", re.I)).click()
        page.wait_for_timeout(3000)
        esperar_carregar(page, 2000)
        botao = page.get_by_role("button", name=re.compile("Exportar Excel", re.I)).first
        limite = time.monotonic() + 90
        while not botao.is_enabled():
            if time.monotonic() > limite:
                msg = page.locator("xpath=//*[contains(., 'Resultado da busca')]/following-sibling::*[1]")
                aviso = msg.first.inner_text(timeout=2000).strip() if msg.count() else ""
                raise RuntimeError(f"Yelum ({filtro}): Exportar Excel não liberou. Portal: {aviso!r}")
            page.wait_for_timeout(1000)
        with page.expect_download(timeout=LIMITE) as info:
            botao.click()
        destino = config.PASTA_DOWNLOADS / nome_arquivo
        info.value.save_as(destino)
        return destino

    # ---------------------------------------------------------- conversão
    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        arquivo = Path(arquivo)
        partes = [self._ler(arquivo, so_vencidas=False)]
        a_vencer = arquivo.with_name(arquivo.name.replace("atrasadas", "avencer"))
        if a_vencer != arquivo and a_vencer.exists():
            partes.append(self._ler(a_vencer, so_vencidas=True))
        linhas = [l for p in partes for l in p]
        return montar_padrao(self.nome, linhas)

    @staticmethod
    def _ler(arquivo: Path, so_vencidas: bool) -> list[dict]:
        df = ler_tabela(arquivo, cabecalho_com=("Apólice", "Apolice"))
        c = {
            "apolice": achar_coluna(df, "APOLICE"),
            "nome": achar_coluna(df, "NOME"),
            "produto": achar_coluna(df, "PRODUTO"),
            "parcela": achar_coluna(df, "PARCELA"),
            "venc_atual": achar_coluna(df, "VENCIMENTOATUAL", "VENCIMENTO_ATUAL"),
            "venc_original": achar_coluna(df, "VENCIMENTOORIGINAL", "VENCIMENTO_ORIGINAL"),
            "valor": achar_coluna(df, "VALOR"),
            "tipo": achar_coluna(df, "TIPO", "FORMA"),
            "status": achar_coluna(df, "STATUS"),
            "motivo": achar_coluna(df, "MOTIVOREJEICAO", "MOTIVO"),
        }
        if not c["apolice"] or not (c["venc_original"] or c["venc_atual"]):
            raise ValueError(f"Layout do relatório Yelum mudou. Colunas: {list(df.columns)}")

        def v(l, k):
            return l[c[k]] if c[k] else None

        hoje = date.today()
        linhas = []
        for _, l in df.iterrows():
            if not texto(v(l, "apolice")):
                continue
            original = para_data(v(l, "venc_original")) or para_data(v(l, "venc_atual"))
            atual = para_data(v(l, "venc_atual"))
            pagamento = forma_pagamento(v(l, "tipo"))
            limite = None
            if so_vencidas:
                # "A Vencer": só entram parcelas que ficaram em aberto e a seguradora
                # reprogramou para PIX ou BOLETO (vencimento original já passou).
                # O vencimento reprogramado é o prazo limite para pagamento.
                if not (original and original < hoje) or pagamento not in ("PIX", "BOLETO"):
                    continue
                limite = atual
            produto = texto(v(l, "produto")).upper()
            status = texto(v(l, "status"))
            motivo = texto(v(l, "motivo")).strip(" -")
            if original and original < hoje and re.search(r"a vencer", status, re.I):
                # parcela "A Vencer" no portal, mas com o vencimento original já passado
                status = f"{status} (venc. original passou" + (
                    f"; reprogramada p/ {atual:%d/%m/%Y})" if atual and atual != original else ")")
            linhas.append({
                "SEGURADORA": "ALIRO" if "ALIRO" in produto else "YELUM",
                "SEGURADO": texto(v(l, "nome")),
                "APÓLICE": texto(v(l, "apolice")),
                "RAMO": texto(v(l, "produto")),
                "PARCELA": texto(v(l, "parcela")),
                "VENCIMENTO": original,
                "VALOR": para_numero(v(l, "valor")),
                "PAGAMENTO": pagamento,
                "DATA LIMITE": limite,
                "SITUAÇÃO": f"{status} — {motivo}" if motivo else status,
            })
        return linhas
