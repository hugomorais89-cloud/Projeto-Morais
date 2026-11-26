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

import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from ..navegador import clicar_texto, esperar_carregar
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
log = logging.getLogger("robo")
LIMITE = 120_000  # ms — o sistema de parcelas da Allianz é lento para abrir


class Allianz(Seguradora):
    nome = "ALLIANZ"

    # ------------------------------------------------------------ navegação
    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("ALLIANZ")
        log.info("Abrindo AllianzNet e fazendo login")
        page.goto(URL_HOME, wait_until="domcontentloaded")
        self._login(page, usuario, senha)

        log.info("Menu: Gestão > Financeiro > Gestão de Parcelas")
        clicar_texto(page, "Gestão", exato=True)
        clicar_texto(page, "Financeiro")
        clicar_texto(page, "Gestão de Parcelas")

        # A tela de parcelas é um sistema antigo carregado dentro de um iframe
        tela = self._quadro_parcelas(page)
        log.info("Abrindo aba Gestão de Inadimplentes (pode levar ~1 min)")
        tela.locator("#irGestaoInadimplentes:visible").first.click(timeout=LIMITE)
        tela.locator("#dtInicio").wait_for(state="visible", timeout=LIMITE)

        hoje = date.today()
        inicio = hoje - timedelta(days=config.DIAS_RETROATIVOS)
        log.info("Filtro: Inadimplente, vencimento de %s a %s", f"{inicio:%d/%m/%Y}", f"{hoje:%d/%m/%Y}")
        # Status = Inadimplente (valor "1"). O <select> fica oculto atrás de um
        # componente visual, por isso é definido via JavaScript.
        tela.locator("#status").evaluate(
            "e => { e.value = '1'; e.dispatchEvent(new Event('change', {bubbles: true}));"
            " if (window.jQuery && jQuery(e).selectpicker) jQuery(e).selectpicker('refresh'); }"
        )
        for seletor, valor in (("#dtInicio", inicio), ("#dtFim", hoje)):
            campo = tela.locator(seletor)
            campo.click()
            campo.fill(f"{valor:%d/%m/%Y}")
            campo.press("Escape")  # fecha o calendário

        tela.locator("#cmdPesquisar").click()
        botao = tela.locator("#cmdGerarArquivo")
        botao.wait_for(state="visible", timeout=LIMITE)

        log.info("Gerando planilha")
        with page.expect_download(timeout=LIMITE) as info:
            botao.click()
        download = info.value
        extensao = Path(download.suggested_filename).suffix or ".csv"
        destino = config.PASTA_DOWNLOADS / f"allianz_{date.today():%Y-%m-%d}{extensao}"
        download.save_as(destino)
        return destino

    @staticmethod
    def _quadro_parcelas(page):
        """Espera o iframe do sistema de parcelas (endereço contém 'drbl13')."""
        for _ in range(LIMITE // 1000):
            for frame in page.frames:
                if "/drbl13/" in frame.url:
                    return frame
            page.wait_for_timeout(1000)
        raise TimeoutError("Tela de Gestão de Parcelas não carregou")

    def _login(self, page, usuario: str, senha: str) -> None:
        campo_senha = page.locator("input[name=password]")
        try:
            campo_senha.wait_for(state="visible", timeout=30_000)
        except Exception:
            if "/private/" in page.url:
                return  # já está logado
            raise
        page.locator("input[name=username]").fill(usuario)
        campo_senha.fill(senha)
        page.get_by_role("button", name="Iniciar sessão").click()
        try:
            page.wait_for_url(re.compile(r"/private/"), timeout=60_000)
        except Exception:
            raise RuntimeError("Login na Allianz falhou — verifique usuário/senha no .env")
        esperar_carregar(page, 2000)

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
