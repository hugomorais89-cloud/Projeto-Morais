"""Suhai Seguradora — portal i4pro.

Caminho no portal (conforme vídeo da equipe):
  i4pro.suhaiseguradora.com.br > login > Relatórios > Impressão de 2ª Via
  > Formulário "Parcelas Pendentes Corretor" > Empresa SUHAI SEGURADORA S/A
  > Data inicial (DIAS_RETROATIVOS atrás) / Data final (hoje) > Exportar Excel > XLSX
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
URL = "https://i4pro.suhaiseguradora.com.br/"
LIMITE = 120_000


class Suhai(Seguradora):
    nome = "SUHAI"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("SUHAI")
        log.info("Login no i4pro Suhai")
        # Enviar o login antes de a página terminar de carregar dá "Sessão inválida":
        # espera o load completo e digita devagar nos campos do i4pro
        page.goto(URL, wait_until="load")
        esperar_carregar(page, 3000)
        campo_login = page.locator("#cd_usuario")
        if campo_login.count():
            campo_login.click()
            campo_login.press_sequentially(usuario, delay=50)
            campo_senha = page.locator("#nm_senha")
            campo_senha.click()
            campo_senha.press_sequentially(senha, delay=50)
            page.wait_for_timeout(500)
            page.locator("#botaoEntrar").click()
        else:
            login_generico(page, usuario, senha)
        try:
            achar(page, lambda f: f.get_by_text(re.compile(r"^\s*Relat[óo]rios\s*$", re.I)),
                  tempo=LIMITE / 1000)
        except Exception:
            raise RuntimeError("Login na Suhai falhou — verifique usuário/senha no .env")
        esperar_carregar(page, 2000)

        log.info("Relatórios > Impressão de 2ª Via")
        achar(page, lambda f: f.get_by_text(re.compile(r"^\s*Relat[óo]rios\s*$", re.I))).click()
        page.wait_for_timeout(1000)
        achar(page, lambda f: f.get_by_text(re.compile(r"Impress[ãa]o de 2", re.I))).click()
        esperar_carregar(page, 3000)

        # As opções usam espaço não separável (\xa0): escolhe pelo texto normalizado.
        # ID000000189 = "Parcelas Pendentes Corretor" (não confundir com o ID001000264
        # "Parcelas Pendentes/Pagas Corretor")
        log.info("Formulário: Parcelas Pendentes Corretor")
        form = achar(page, lambda f: f.locator("select#id_formulario"), tempo=60)
        self._escolher(form, r"Parcelas Pendentes Corretor")
        esperar_carregar(page, 3000)
        empresa = achar(page, lambda f: f.locator("select#cd_empresa"), tempo=30, obrigatorio=False)
        if empresa is not None:
            self._escolher(empresa, r"SUHAI SEGURADORA")
            page.wait_for_timeout(1500)

        hoje = date.today()
        inicio = hoje - timedelta(days=config.DIAS_RETROATIVOS)
        log.info("Período: %s a %s", f"{inicio:%d/%m/%Y}", f"{hoje:%d/%m/%Y}")
        for seletor, valor in (("input#dt_inicio", inicio), ("input#dt_fim", hoje)):
            campo = achar(page, lambda f, s=seletor: f.locator(s), tempo=30)
            campo.click()
            campo.fill(f"{valor:%d/%m/%Y}")
            campo.press("Tab")
            page.wait_for_timeout(400)
            if campo.input_value() != f"{valor:%d/%m/%Y}":
                campo.click()
                campo.press("Control+a")
                campo.press_sequentially(f"{valor:%d/%m/%Y}", delay=60)
                campo.press("Tab")

        log.info("Exportar Excel")
        achar(page, lambda f: f.get_by_text(re.compile(r"^\s*Exportar Excel\s*$", re.I))).click()
        page.wait_for_timeout(2000)
        page.on("dialog", lambda d: d.accept())  # "Office 2003 possui limitação..." (só no XLS)
        # Modal "Exportação" (página principal): botões #btn-modal-xls / -xlsx / -csv
        formato = achar(page, lambda f: f.locator("#btn-modal-xlsx"), tempo=30)
        with page.expect_download(timeout=LIMITE) as info:
            formato.click()
            ok = achar(page, lambda f: f.get_by_role("button", name=re.compile(r"^\s*ok\s*$", re.I)),
                       tempo=3, obrigatorio=False)
            if ok is not None:
                ok.click()
        download = info.value
        extensao = Path(download.suggested_filename).suffix or ".xlsx"
        destino = config.PASTA_DOWNLOADS / f"suhai_{hoje:%Y-%m-%d}{extensao}"
        download.save_as(destino)
        return destino

    @staticmethod
    def _escolher(select, padrao: str) -> None:
        """Seleciona a opção cujo texto (com \\xa0 trocado por espaço) casa com `padrao`."""
        opcoes = select.locator("option").evaluate_all(
            "os => os.map(o => [o.value, o.text.replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim()])")
        valor = next((v for v, t in opcoes if re.search(padrao, t, re.I)), None)
        if valor is None:
            raise RuntimeError(f"Suhai: opção {padrao!r} não encontrada em {[t for _, t in opcoes]}")
        select.select_option(value=valor)

    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        df = ler_tabela(arquivo, cabecalho_com=("cd_apolice", "nm_pessoa_sub", "Segurado", "Apólice"))
        log.info("Suhai — colunas do arquivo: %s", list(df.columns))
        c = {
            "segurado": achar_coluna(df, "NM_PESSOA_SUB", "SEGURADO", "NOME", "CLIENTE"),
            "cpf": achar_coluna(df, "CPF", "CNPJ"),
            "apolice": achar_coluna(df, "CD_APOLICE", "APOLICE"),
            "ramo": achar_coluna(df, "RAMO", "PRODUTO"),
            "parcela": achar_coluna(df, "NR_PARCELA", "PARCELA"),
            "vencimento": achar_coluna(df, "DT_VENCIMENTO", "VENCIMENTO"),
            "valor": achar_coluna(df, "VL_TOTAL", "VALOR", "PREMIO"),
            "pagamento": achar_coluna(df, "NM_FORMA_PAGAMENTO", "FORMA", "MEIO"),
            "telefone": achar_coluna(df, "TELEFONE", "CELULAR", "FONE"),
            "situacao": achar_coluna(df, "SITUACAO", "STATUS"),
        }
        if not c["vencimento"] or not (c["segurado"] or c["apolice"]):
            raise ValueError(f"Layout do relatório Suhai não reconhecido. Colunas: {list(df.columns)}")

        def v(l, k):
            return l[c[k]] if c[k] else None

        hoje = date.today()
        linhas = []
        for _, l in df.iterrows():
            if not (texto(v(l, "segurado")) or texto(v(l, "apolice"))):
                continue
            venc = para_data(v(l, "vencimento"))
            if venc and venc > hoje:
                continue  # ainda não venceu (as que vencem hoje entram, como nas outras)
            linhas.append({
                "SEGURADO": texto(v(l, "segurado")),
                "CPF/CNPJ": re.sub(r"\D", "", texto(v(l, "cpf"))),
                "APÓLICE": texto(v(l, "apolice")),
                "RAMO": texto(v(l, "ramo")),
                "PARCELA": texto(v(l, "parcela")),
                "VENCIMENTO": venc,
                "VALOR": para_numero(v(l, "valor")),
                "TELEFONE": texto(v(l, "telefone")),
                "PAGAMENTO": forma_pagamento(v(l, "pagamento")),
                "SITUAÇÃO": texto(v(l, "situacao")) or "Pendente",
            })
        return montar_padrao(self.nome, linhas)
