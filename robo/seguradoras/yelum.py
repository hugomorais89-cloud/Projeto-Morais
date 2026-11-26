"""Yelum Seguros (inclui ALIRO) — Novo Meu Espaço Corretor.

Caminho no portal (conforme vídeo da equipe):
  login > Financeiro > Gestão de Parcelas > aceitar "Termo de adesão" (LGPD)
  1) filtro "Atrasadas", vencimento de <90 dias atrás> até <hoje> > Buscar > Exportar Excel
  2) filtro "A Vencer", de <hoje> até <+30 dias> > Buscar > Exportar Excel
     → a equipe aproveita só as parcelas "A Vencer" cujo VENCIMENTO ORIGINAL já passou
       (foram reprogramadas, mas continuam pendentes).

Colunas do Excel: Apólice, Emissão, Nome, Produto, Parcela, VencimentoAtual, Valor,
  Tipo, Status, VencimentoOriginal, IOF, MotivoRejeicao, DataRejeicao, NomeCorretora
O PRODUTO indica a seguradora: "ALIRO SEGURO AUTO..." → ALIRO; "YELUM AUTO..." → YELUM.

⚠ Ainda não testado no portal real (o site recusa conexões de fora do Brasil).
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
URL = "https://novomeuespacocorretor.yelumseguros.com.br/"
LIMITE = 120_000
DIAS_A_VENCER = 30


class Yelum(Seguradora):
    nome = "YELUM / ALIRO"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("YELUM")
        log.info("Login no Meu Espaço Corretor")
        page.goto(URL, wait_until="domcontentloaded")
        login_generico(page, usuario, senha)
        try:
            page.get_by_text("Financeiro").first.wait_for(timeout=LIMITE)
        except Exception:
            raise RuntimeError("Login na Yelum falhou — verifique usuário/senha no .env")
        esperar_carregar(page, 2000)

        log.info("Financeiro > Gestão de Parcelas")
        page.get_by_text("Financeiro").first.hover()
        page.get_by_text("Gestão de Parcelas").first.click(timeout=LIMITE)
        self._aceitar_termo(page)

        hoje = date.today()
        atrasadas = self._exportar(page, "Atrasadas", hoje - timedelta(days=config.DIAS_RETROATIVOS),
                                   hoje, f"yelum_atrasadas_{hoje:%Y-%m-%d}.xlsx")
        try:
            self._exportar(page, "A Vencer", hoje, hoje + timedelta(days=DIAS_A_VENCER),
                           f"yelum_avencer_{hoje:%Y-%m-%d}.xlsx")
        except Exception:
            log.warning("Não foi possível exportar 'A Vencer' — seguindo só com 'Atrasadas'",
                        exc_info=True)
        return atrasadas

    @staticmethod
    def _aceitar_termo(page) -> None:
        caixa = achar(page, lambda f: f.get_by_text(re.compile("Declaro que li", re.I)),
                      tempo=20, obrigatorio=False)
        if caixa is None:
            return
        log.info("Aceitando termo de adesão (LGPD)")
        caixa.click()
        page.get_by_role("button", name=re.compile(r"^\s*concordo\s*$", re.I)).click()
        page.wait_for_timeout(1500)

    @staticmethod
    def _exportar(page, filtro: str, inicio: date, fim: date, nome_arquivo: str) -> Path:
        log.info("Filtro %s: %s a %s", filtro, f"{inicio:%d/%m/%Y}", f"{fim:%d/%m/%Y}")
        combo = page.locator("select:visible").first
        if combo.count():
            combo.select_option(label=filtro)
        else:
            page.get_by_text(re.compile(r"Escolha um filtro|Atrasadas|A Vencer", re.I)).first.click()
            page.get_by_text(filtro, exact=True).last.click()
        datas = page.locator("input[placeholder*='dd/mm' i]:visible")
        for i, valor in ((0, inicio), (1, fim)):
            campo = datas.nth(i)
            campo.click()
            campo.fill(f"{valor:%d/%m/%Y}")
            campo.press("Escape")
        page.get_by_role("button", name=re.compile(r"^\s*buscar\s*$", re.I)).click()
        page.wait_for_timeout(3000)
        esperar_carregar(page, 2000)
        botao = page.get_by_role("button", name=re.compile("Exportar Excel", re.I)).first
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
            if so_vencidas and not (original and original < hoje):
                continue
            produto = texto(v(l, "produto")).upper()
            status = texto(v(l, "status"))
            motivo = texto(v(l, "motivo"))
            atual = para_data(v(l, "venc_atual"))
            if so_vencidas and atual:
                status = f"{status} (reprogramada p/ {atual:%d/%m/%Y})"
            linhas.append({
                "SEGURADORA": "ALIRO" if "ALIRO" in produto else "YELUM",
                "SEGURADO": texto(v(l, "nome")),
                "APÓLICE": texto(v(l, "apolice")),
                "RAMO": texto(v(l, "produto")),
                "PARCELA": texto(v(l, "parcela")),
                "VENCIMENTO": original,
                "VALOR": para_numero(v(l, "valor")),
                "PAGAMENTO": forma_pagamento(v(l, "tipo")),
                "SITUAÇÃO": f"{status} — {motivo}" if motivo else status,
            })
        return linhas
