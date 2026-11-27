"""HDI Seguros — HDI Digital.

Caminho no portal (conforme vídeo da equipe):
  hdi.com.br/hdidigital > login > menu "Parcela"
  > Período de vencimento (de/até) > Tipo de Parcelas: ATRASADAS > Buscar
  O portal não exporta Excel (só "Visualizar impressão" → PDF). Por isso o robô lê
  a tabela de resultados direto da tela e grava um CSV em downloads/.

Colunas da tela: Documento/Parcela ("01.053.139.002620.000000 - 05 de 10"), Vencto,
  Limite sem Vistoria, Nome cliente, Valor (R$), Posição, Data de Pagamento,
  Data Prev. Receb., Forma de Pagamento — e abaixo de cada linha
  "Cobertura Proporcional até: dd/mm/aaaa".

Testado no portal real em 26/11/2026:
  - o portal recusa períodos maiores que 30 dias (alerta "Período não pode ser
    superior a 30 dias") → busca sempre os últimos 30 dias;
  - a tela fica no iframe dsp_parcelas_busca_2008.htm e o resultado em
    dsp_parcelas_view_2008.htm; nesta versão não há a linha "Cobertura Proporcional".
"""
from __future__ import annotations

import csv
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .. import config
from ..navegador import achar, achar_todos, clicar_texto, esperar_carregar, login_generico
from .base import (
    Seguradora,
    forma_pagamento,
    ler_tabela,
    montar_padrao,
    para_data,
    para_numero,
    texto,
)

log = logging.getLogger("robo")
URL = "https://www.hdi.com.br/hdidigital"
LIMITE = 120_000
PERIODO_DIAS = 30  # limite do portal: "Período não pode ser superior a 30 dias"
RE_DOC = re.compile(r"(\d{2}\.\d{3}\.\d{3}\.\d{6}\.\d{6})\s*-\s*(\d+)\s*de\s*(\d+)")
RE_COBERTURA = re.compile(r"Cobertura Proporcional at[ée]:?\s*(\d{2}/\d{2}/\d{2,4})", re.I)
CAMPOS = ["documento", "parcela", "total_parcelas", "vencimento", "limite_vistoria",
          "segurado", "valor", "posicao", "data_pagamento", "data_prev", "forma_pagamento",
          "cobertura_ate"]


class Hdi(Seguradora):
    nome = "HDI"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("HDI")
        log.info("Login no HDI Digital")
        page.goto(URL, wait_until="domcontentloaded")
        login_generico(page, usuario, senha, botao=r"entrar")
        try:
            # Há vários "Parcela" escondidos na página; espera pelo item visível do menu
            achar(page, lambda f: f.get_by_text("Parcela", exact=True), tempo=LIMITE / 1000)
        except Exception:
            raise RuntimeError("Login na HDI falhou — verifique usuário/senha no .env")
        esperar_carregar(page, 2000)

        # Alertas do portal (ex.: "Período não pode ser superior a 30 dias") vão para o log
        self._alertas: list[str] = []

        def _alerta(d):
            self._alertas.append(d.message)
            log.warning("HDI — alerta do portal: %s", d.message)
            d.dismiss()
        page.on("dialog", _alerta)

        # O portal só aceita período de até 30 dias: busca os últimos 30 dias até hoje
        # (independe de DIAS_RETROATIVOS)
        hoje = date.today()
        inicio = hoje - timedelta(days=PERIODO_DIAS - 1)
        log.info("Menu Parcela — vencimento de %s a %s", f"{inicio:%d/%m/%Y}", f"{hoje:%d/%m/%Y}")
        clicar_texto(page, "Parcela", exato=True, tempo=60)
        page.wait_for_timeout(2000)
        try:
            datas = achar_todos(
                page, lambda f: f.locator("xpath=//*[contains(., 'PERÍODO DE VENCIMENTO') or "
                                          "contains(., 'Período de Vencimento')]/following::input[@type='text'][position()<=2]"),
                tempo=90)
        except TimeoutError:
            # O firewall da HDI (Akamai) às vezes devolve "Access Denied" dentro da tela Parcela
            def _negado(f):
                try:
                    return "Access Denied" in (f.content() or "")
                except Exception:
                    return False
            if any(_negado(f) for f in page.frames):
                raise RuntimeError("Portal da HDI bloqueou o acesso à tela Parcela (Access Denied) — "
                                   "instabilidade do site; tentar novamente mais tarde") from None
            raise
        for i, valor in ((0, inicio), (1, hoje)):
            campo = datas.nth(i)
            campo.click()
            campo.fill(f"{valor:%d/%m/%Y}")
            campo.press("Escape")

        # Tipo de parcelas = ATRASADAS (só essas entram no relatório)
        tipo = achar(page, lambda f: f.locator("select:visible").filter(
            has=f.locator("option", has_text=re.compile("atrasad", re.I))), tempo=30, obrigatorio=False)
        if tipo is None:
            raise RuntimeError("Campo 'Tipo de Parcelas' com a opção ATRASADAS não encontrado")
        opcoes = tipo.locator("option").all_inner_texts()
        log.info("Tipos de parcela disponíveis: %s", opcoes)
        tipo.select_option(label=next(o for o in opcoes if re.search("atrasad", o, re.I)))

        # BUSCAR é um <button onclick="validacoes()"> dentro do iframe dsp_parcelas_busca
        buscar = achar(page, lambda f: f.get_by_role(
            "button", name=re.compile(r"^\s*buscar\s*$", re.I)), tempo=30)
        buscar.click()
        page.wait_for_timeout(5000)
        esperar_carregar(page, 3000)
        if self._alertas:
            raise RuntimeError(f"HDI recusou a busca: {self._alertas[-1]}")

        linhas = self._ler_resultados(page)
        destino = config.PASTA_DOWNLOADS / f"hdi_{hoje:%Y-%m-%d}.csv"
        with open(destino, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";")
            w.writeheader()
            w.writerows(linhas)
        log.info("HDI: %d parcelas lidas da tela", len(linhas))
        return destino

    def _ler_resultados(self, page) -> list[dict]:
        """Lê todas as páginas da tabela de resultados."""
        vistas: dict[tuple, dict] = {}
        pagina = 1
        while True:
            if achar(page, lambda f: f.get_by_text(RE_DOC), tempo=90, obrigatorio=False) is None:
                if pagina == 1:
                    log.warning("HDI: nenhuma parcela atrasada apareceu na tela")
                break
            for frame in page.frames:
                try:
                    trs = frame.locator("tr").all()
                except Exception:
                    continue
                for i, tr in enumerate(trs):
                    try:
                        celulas = [c.strip() for c in tr.locator("td").all_inner_texts()]
                    except Exception:
                        continue
                    if not celulas or not RE_DOC.search(celulas[0]):
                        continue
                    linha = self._linha(celulas)
                    # "Cobertura Proporcional até" fica na linha seguinte
                    for prox in trs[i + 1:i + 3]:
                        m = RE_COBERTURA.search(prox.inner_text())
                        if m:
                            linha["cobertura_ate"] = m.group(1)
                            break
                    vistas[(linha["documento"], linha["parcela"])] = linha
            pagina += 1
            prox = achar(page, lambda f: f.get_by_role("link", name=str(pagina), exact=True),
                         tempo=3, obrigatorio=False)
            if prox is None:
                break
            prox.click()
            page.wait_for_timeout(4000)
        return list(vistas.values())

    @staticmethod
    def _linha(c: list[str]) -> dict:
        m = RE_DOC.search(c[0])
        datas = [x for x in c[1:] if re.fullmatch(r"\d{2}/\d{2}/\d{2,4}", x)]
        valor = next((x for x in c[1:] if re.fullmatch(r"[\d.]+,\d{2}", x)), "")
        posicao = next((x for x in c if re.search(r"parcela\s", x, re.I) and x != c[0]), "")
        nome = next((x for x in c[1:] if re.search(r"[A-Za-zÀ-ú]{3,}", x)
                     and x not in (posicao,) and not re.search(r"boleto|d[ée]bito|cart|2ª via|pix", x, re.I)), "")
        forma = next((x for x in c if re.search(r"boleto|d[ée]bito|cart[ãa]o|pix", x, re.I)), "")
        return {
            "documento": m.group(1), "parcela": m.group(2), "total_parcelas": m.group(3),
            "vencimento": datas[0] if datas else "", "limite_vistoria": datas[1] if len(datas) > 1 else "",
            "segurado": nome, "valor": valor, "posicao": re.sub(r"\s+", " ", posicao),
            "data_pagamento": "", "data_prev": "", "forma_pagamento": forma, "cobertura_ate": "",
        }

    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        df = ler_tabela(arquivo)
        linhas = []
        for _, l in df.iterrows():
            posicao = texto(l.get("POSICAO"))
            if re.search(r"\bpaga\b", posicao, re.I):
                continue
            limite = texto(l.get("LIMITE_VISTORIA"))
            linhas.append({
                "SEGURADO": texto(l.get("SEGURADO")),
                "APÓLICE": texto(l.get("DOCUMENTO")),
                "PARCELA": texto(l.get("PARCELA")),
                "VENCIMENTO": para_data(l.get("VENCIMENTO")),
                "VALOR": para_numero(l.get("VALOR")),
                "PREV. CANCELAMENTO": para_data(l.get("COBERTURA_ATE")),
                "PAGAMENTO": forma_pagamento(l.get("FORMA_PAGAMENTO")),
                "SITUAÇÃO": posicao + (f" · limite s/ vistoria {limite}" if limite else ""),
            })
        return montar_padrao(self.nome, linhas)
