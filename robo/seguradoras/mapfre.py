"""MAPFRE — MAPFRE Negócios (Portal do Corretor).

Caminho no portal (conforme vídeo da equipe):
  negocios.mapfre.com.br/acesso > login > "Selecione o código interno":
  Corretora H MORAIS CORR DE SEGS LTDA, Código interno TODOS > Salvar
  > Financeiro > Parcelas dos Clientes (/parcelas)
  1) Status "Vencida", período dos últimos 30 dias até hoje > Pesquisar > exportar (CSV)
  2) Status "A vencer", período de hoje até +14 dias, "Parcelas Reprogramadas" marcada
     > Pesquisar > exportar (CSV) → entram TODAS as reprogramadas (orientação da equipe).
     Nelas, VENCIMENTO = vencimento original e DATA LIMITE = vencimento reprogramado.

CSV: Nome do Cliente, Código Produto, Descrição Produto, Apólice, Número Endosso,
  Nº Parcela, Valor Parcela, Forma Pagamento, Vencimento (2 colunas), Status,
  Data do Pagamento, Código Interno, Histórico Parcela.
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
    chave,
    forma_pagamento,
    ler_tabela,
    montar_padrao,
    para_data,
    para_numero,
    texto,
)

log = logging.getLogger("robo")
URL = "https://negocios.mapfre.com.br/acesso"
URL_PARCELAS = "https://negocios.mapfre.com.br/parcelas"
LIMITE = 120_000
PERIODO_VENCIDAS = 30
DIAS_REPROGRAMADAS = 14


class Mapfre(Seguradora):
    nome = "MAPFRE"

    def baixar(self, page) -> Path:
        usuario, senha = config.credencial("MAPFRE")
        log.info("Login no MAPFRE Negócios")
        page.goto(URL, wait_until="load")
        esperar_carregar(page, 3000)
        # Aviso "Informação de proteção de dados" (só informativo, sem aceite): fecha no X
        fechar = achar(page, lambda f: f.locator(".custom-close-button, .icon-CLOSE"),
                       tempo=15, obrigatorio=False)
        if fechar is not None:
            log.info("Fechando aviso de proteção de dados")
            fechar.click()
            page.wait_for_timeout(1000)
        # Campos Ionic: digitar devagar e clicar no ion-button "Entrar"
        campo_senha = achar(page, lambda f: f.locator("input[type=password]"), tempo=60)
        campo_usuario = page.locator("input.native-input:not([type=password])").first
        campo_usuario.click()
        campo_usuario.press_sequentially(usuario, delay=40)
        campo_senha.click()
        campo_senha.press_sequentially(senha, delay=40)
        page.wait_for_timeout(500)
        entrar = page.locator("ion-button.loginButton")
        if entrar.count():
            entrar.first.click()
        else:
            login_generico(page, usuario, senha)
        self._codigo_interno(page)

        hoje = date.today()
        vencidas = self._exportar(page, "Vencida", hoje - timedelta(days=PERIODO_VENCIDAS), hoje,
                                  reprogramadas=False, nome=f"mapfre_vencidas_{hoje:%Y-%m-%d}")
        try:
            self._exportar(page, "A vencer", hoje, hoje + timedelta(days=DIAS_REPROGRAMADAS),
                           reprogramadas=True, nome=f"mapfre_reprogramadas_{hoje:%Y-%m-%d}")
        except Exception:
            log.warning("MAPFRE: não foi possível exportar as reprogramadas — seguindo só com vencidas",
                        exc_info=True)
        return vencidas

    @staticmethod
    def _codigo_interno(page) -> None:
        """Janela 'Selecione o código interno' logo após o login: escolhe TODOS e salva."""
        titulo = achar(page, lambda f: f.get_by_text(re.compile("Selecione o c[óo]digo interno", re.I)),
                       tempo=LIMITE / 1000, obrigatorio=False)
        if titulo is None:
            if achar(page, lambda f: f.get_by_text(re.compile(r"^\s*Financeiro", re.I)),
                     tempo=5, obrigatorio=False) is None:
                raise RuntimeError("Login na MAPFRE falhou — verifique usuário/senha no .env")
            return
        log.info("Código interno: TODOS")
        page.wait_for_timeout(1500)
        campo = page.get_by_text(re.compile(r"^\s*C[óo]digo interno\s*$", re.I)).last
        campo.locator("xpath=following::*[self::select or @role='combobox' or "
                      "contains(@class,'select')][1]").first.click()
        page.wait_for_timeout(1000)
        achar(page, lambda f: f.get_by_text(re.compile(r"^\s*TODOS\s*$", re.I))).click()
        page.wait_for_timeout(800)
        achar(page, lambda f: f.get_by_role("button", name=re.compile(r"^\s*salvar\s*$", re.I))).click()
        esperar_carregar(page, 3000)

    def _exportar(self, page, status: str, inicio: date, fim: date, reprogramadas: bool,
                  nome: str) -> Path:
        log.info("Parcelas dos Clientes — %s, %s a %s%s", status, f"{inicio:%d/%m/%Y}",
                 f"{fim:%d/%m/%Y}", " (reprogramadas)" if reprogramadas else "")
        page.goto(URL_PARCELAS, wait_until="domcontentloaded")
        esperar_carregar(page, 3000)
        achar(page, lambda f: f.get_by_text(re.compile("Parcelas dos Clientes", re.I)), tempo=90)

        # Ordem importa: marcar "Reprogramadas" volta o status para "Vencida",
        # então o status é escolhido por último e conferido antes de pesquisar.
        # "Parcelas Reprogramadas" = ion-checkbox selectedPlot2
        caixa = page.locator("ion-checkbox[formcontrolname=selectedPlot2]")
        if caixa.count() and caixa.evaluate("e => !!e.checked") != reprogramadas:
            caixa.click()
            page.wait_for_timeout(500)

        # Período: ion-input único "dd/mm/aaaa-dd/mm/aaaa" (o clique abre um calendário;
        # define o valor direto no componente e avisa o Angular)
        texto_periodo = f"{inicio:%d/%m/%Y}-{fim:%d/%m/%Y}"
        valor = page.evaluate(r"""(p) => {
            const inp = [...document.querySelectorAll('ion-input')]
                .find(i => /\d{2}\/\d{2}\/\d{4}-/.test(i.value || ''));
            if (!inp) return null;
            inp.value = p;
            inp.dispatchEvent(new CustomEvent('ionInput', {detail: {value: p}}));
            inp.dispatchEvent(new CustomEvent('ionChange', {detail: {value: p}}));
            return inp.value; }""", texto_periodo)
        if valor != texto_periodo:
            raise RuntimeError(f"MAPFRE: não consegui definir o período {texto_periodo} ({valor!r})")

        # Status da Parcela: ion-select que abre um action sheet
        # (Todos, Pago, A vencer, Vencida, Aguardando Empenho)
        seletor_status = page.locator("ion-select[formcontrolname=policyStatusCode]")
        seletor_status.click()
        page.wait_for_timeout(1500)
        page.locator("ion-action-sheet button, ion-alert button, ion-popover ion-item").filter(
            has_text=status).first.click()
        page.wait_for_timeout(500)
        ok = page.locator("ion-alert button").filter(has_text=re.compile(r"^\s*(OK|Confirmar)\s*$", re.I))
        if ok.count():
            ok.first.click()
        page.wait_for_timeout(800)
        log.info("Status selecionado (código %s)", seletor_status.evaluate("e => e.value"))

        exibido = seletor_status.evaluate(
            "e => (e.shadowRoot && e.shadowRoot.textContent || e.textContent || '').trim()")
        if status.lower() not in exibido.lower():
            raise RuntimeError(f"MAPFRE: status ficou {exibido!r} em vez de {status!r}")

        page.locator("ion-button, button").filter(has_text=re.compile(r"^\s*Pesquisar\s*$", re.I)).first.click()
        page.wait_for_timeout(3000)
        esperar_carregar(page, 2000)
        achar(page, lambda f: f.get_by_text(re.compile(r"Exibindo|Nenhuma|n[ãa]o (foram )?encontrad", re.I)),
              tempo=90)
        titulo = page.get_by_text(re.compile(r"Parcelas dos Clientes")).first.inner_text()
        log.info("MAPFRE: %s", titulo.strip())

        # Ícone de planilha abaixo da tabela (exporta CSV)
        botao = achar(page, lambda f: f.locator("span.icon-file-excel"), tempo=30)
        with page.expect_download(timeout=LIMITE) as info:
            botao.click()
        download = info.value
        extensao = Path(download.suggested_filename).suffix or ".csv"
        destino = config.PASTA_DOWNLOADS / f"{nome}{extensao}"
        download.save_as(destino)
        return destino

    # ---------------------------------------------------------- conversão
    def normalizar(self, arquivo: Path) -> pd.DataFrame:
        arquivo = Path(arquivo)
        partes = [self._ler(arquivo, reprogramadas=False)]
        for irmao in arquivo.parent.glob(arquivo.stem.replace("vencidas", "reprogramadas") + ".*"):
            if irmao != arquivo:
                partes.append(self._ler(irmao, reprogramadas=True))
        return montar_padrao(self.nome, [l for p in partes for l in p])

    @staticmethod
    def _ler(arquivo: Path, reprogramadas: bool) -> list[dict]:
        df = ler_tabela(arquivo)
        log.info("MAPFRE — colunas de %s: %s", arquivo.name, list(df.columns))
        vencs = [col for col in df.columns if chave(col).startswith("VENCIMENTO")]
        c = {
            "nome": achar_coluna(df, "NOME"),
            "produto": achar_coluna(df, "DESCRICAO", "PRODUTO"),
            "apolice": achar_coluna(df, "APOLICE"),
            "parcela": achar_coluna(df, "N_PARCELA", "NO_PARCELA", "PARCELA"),
            "valor": achar_coluna(df, "VALOR"),
            "forma": achar_coluna(df, "FORMA"),
            "status": achar_coluna(df, "STATUS"),
            "historico": achar_coluna(df, "HISTORICO"),
            "cpf": achar_coluna(df, "CPF", "CNPJ"),
        }
        orig = next((v for v in vencs if "ORIG" in v), None)
        atual = next((v for v in vencs if v != orig), None)
        if not c["apolice"] or not vencs:
            raise ValueError(f"Layout do relatório MAPFRE não reconhecido. Colunas: {list(df.columns)}")

        def v(l, k):
            return l[c[k]] if c[k] else None

        linhas = []
        for _, l in df.iterrows():
            if not texto(v(l, "apolice")):
                continue
            data_atual = para_data(l[atual]) if atual else None
            data_orig = para_data(l[orig]) if orig else None
            status = texto(v(l, "status"))
            hist = texto(v(l, "historico"))
            linha = {
                "SEGURADO": texto(v(l, "nome")),
                "CPF/CNPJ": re.sub(r"\D", "", texto(v(l, "cpf"))),
                "APÓLICE": texto(v(l, "apolice")),
                "RAMO": texto(v(l, "produto")),
                "PARCELA": texto(v(l, "parcela")),
                "VALOR": para_numero(v(l, "valor")),
                "PAGAMENTO": forma_pagamento(v(l, "forma")),
            }
            if reprogramadas:
                linha["VENCIMENTO"] = data_orig or data_atual
                linha["DATA LIMITE"] = data_atual if data_orig else None
                rep = f"; reprogramada p/ {data_atual:%d/%m/%Y}" if data_orig and data_atual else ""
                linha["SITUAÇÃO"] = f"Reprogramada ({status}{rep})"
            else:
                linha["VENCIMENTO"] = data_orig or data_atual
                linha["SITUAÇÃO"] = status
            if hist:
                linha["SITUAÇÃO"] += f" — {hist}"
            linhas.append(linha)
        return linhas
