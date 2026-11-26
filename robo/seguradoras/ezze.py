"""EZZE Seguros — Portal do Corretor.

Arquivo Parcelas_Atraso.xlsx (conferido com o arquivo real de 26/11/2026):
  Apólice, Endosso, Nome do Segurado, Parcela, Data Vencimento, Valor, Indicador de Atraso

Caminho no portal (conforme vídeo da equipe):
  portal.ezzeseguros.com.br/Portal/Landing > ACESSAR > login > página inicial
  > seção "Minha gestão" > card "Parcelas em atraso" > Download (Parcelas_Atraso.xlsx)

Testado no portal real em 26/11/2026. O login só funciona depois de aceitar
  o aviso de cookies essenciais (barra no rodapé).
  O layout da planilha é lido de forma flexível; se alguma coluna não for
  reconhecida o robô avisa no log quais colunas encontrou.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import pandas as pd

from .. import config
from ..navegador import esperar_carregar, login_generico
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
URL = "https://portal.ezzeseguros.com.br/Portal/Landing/"
LIMITE = 120_000


class Ezze(Seguradora):
    nome = "EZZE"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("EZZE")
        log.info("Abrindo portal EZZE")
        page.goto(URL, wait_until="domcontentloaded")
        acessar = page.get_by_text(re.compile(r"^\s*acessar\s*$", re.I)).first
        if acessar.count():
            acessar.click()
        self._aceitar_cookies(page)
        login_generico(page, usuario, senha, botao=r"entrar")
        try:
            page.wait_for_url(re.compile(r"PortalCorretor", re.I), timeout=LIMITE)
        except Exception:
            raise RuntimeError("Login na EZZE falhou — verifique usuário/senha no .env")
        esperar_carregar(page, 3000)

        log.info("Card 'Parcelas em atraso' > Download")
        card = page.locator("div").filter(
            has=page.get_by_text("Parcelas em atraso", exact=True)
        ).filter(has=page.get_by_text("Download", exact=True)).last
        card.scroll_into_view_if_needed(timeout=LIMITE)
        botao = card.get_by_text("Download", exact=True)
        with page.expect_download(timeout=LIMITE) as info:
            botao.click()
        download = info.value
        extensao = Path(download.suggested_filename).suffix or ".xlsx"
        destino = config.PASTA_DOWNLOADS / f"ezze_{date.today():%Y-%m-%d}{extensao}"
        download.save_as(destino)
        return destino

    @staticmethod
    def _aceitar_cookies(page) -> None:
        """O login só funciona depois de aceitar o termo de cookies (barra no rodapé)."""
        aceitar = page.get_by_role("button", name=re.compile(r"^\s*aceitar\s*$", re.I)).or_(
            page.get_by_text(re.compile(r"^\s*aceitar\s*$", re.I))).first
        try:
            aceitar.wait_for(state="visible", timeout=20_000)
            aceitar.click()
            log.info("Termo de cookies aceito")
            page.wait_for_timeout(1000)
        except Exception:
            log.info("Aviso de cookies não apareceu (já aceito)")
        # Pop-up "Por favor aceite a política de cookies" pode ter ficado aberto
        ok = page.get_by_role("button", name=re.compile(r"^\s*ok\s*$", re.I)).first
        try:
            if ok.is_visible():
                ok.click()
        except Exception:
            pass

    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        df = ler_tabela(arquivo, cabecalho_com=("Apólice", "Apolice", "Segurado", "Parcela"))
        c = {
            "segurado": achar_coluna(df, "SEGURADO", "NOME", "CLIENTE"),
            "cpf": achar_coluna(df, "CPF", "CNPJ", "DOCUMENTO"),
            "apolice": achar_coluna(df, "APOLICE"),
            "endosso": achar_coluna(df, "ENDOSSO", "END"),
            "ramo": achar_coluna(df, "RAMO", "PRODUTO"),
            "parcela": achar_coluna(df, "PARCELA", "PARC"),
            "vencimento": achar_coluna(df, "VENCIMENTO", "VENC", "DT_VENC", "DATA_VENC"),
            "valor": achar_coluna(df, "VALOR", "PREMIO"),
            "pagamento": achar_coluna(df, "FORMA", "MEIO", "TIPO_PAG"),
            "telefone": achar_coluna(df, "TELEFONE", "CELULAR", "FONE"),
            "situacao": achar_coluna(df, "STATUS", "SITUACAO"),
            "atraso": achar_coluna(df, "INDICADOR_DE_ATRASO", "INDICADOR"),
            "cancelamento": achar_coluna(df, "CANCEL", "VIGENCIA"),
        }
        log.info("EZZE — colunas do arquivo: %s", list(df.columns))
        faltando = [k for k in ("vencimento",) if not c[k]] + (
            [] if c["segurado"] or c["apolice"] else ["segurado/apólice"])
        if faltando:
            raise ValueError(f"Layout do relatório EZZE não reconhecido — faltam {faltando}. "
                             f"Colunas: {list(df.columns)}")

        def v(l, k):
            return l[c[k]] if c[k] else None

        linhas = []
        for _, l in df.iterrows():
            if not (texto(v(l, "segurado")) or texto(v(l, "apolice"))):
                continue
            if c["atraso"] and texto(v(l, "atraso")).upper() in ("NAO", "NÃO", "N"):
                continue  # o relatório marca se a parcela está de fato em atraso
            linhas.append({
                "SEGURADO": texto(v(l, "segurado")),
                "CPF/CNPJ": re.sub(r"\D", "", texto(v(l, "cpf"))),
                "APÓLICE": texto(v(l, "apolice")),
                "RAMO": texto(v(l, "ramo")),
                "PARCELA": texto(v(l, "parcela")),
                "VENCIMENTO": para_data(v(l, "vencimento")),
                "VALOR": para_numero(v(l, "valor")),
                "PREV. CANCELAMENTO": para_data(v(l, "cancelamento")),
                "TELEFONE": texto(v(l, "telefone")),
                "PAGAMENTO": forma_pagamento(v(l, "pagamento")),
                "SITUAÇÃO": texto(v(l, "situacao")) or "Em atraso",
            })
        return montar_padrao(self.nome, linhas)
