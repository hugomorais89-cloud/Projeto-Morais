"""Robô de extração de inadimplência.

Uso:
  python -m robo                       # roda todas as seguradoras
  python -m robo allianz               # roda só a Allianz
  python -m robo --arquivo allianz=C:\\caminho\\GESTAO_DE_INADIMPLENTES.csv
                                       # só converte um relatório já baixado
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from . import config
from .consolidar import gerar_planilha
from .seguradoras import SEGURADORAS

log = logging.getLogger("robo")


def configurar_log() -> Path:
    arq = config.PASTA_LOGS / f"execucao_{datetime.now():%Y-%m-%d_%H%M}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%d/%m %H:%M:%S",
        handlers=[logging.FileHandler(arq, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    return arq


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extrai inadimplência das seguradoras")
    ap.add_argument("seguradoras", nargs="*", help=f"opções: {', '.join(SEGURADORAS)}")
    ap.add_argument("--arquivo", action="append", default=[], metavar="SEGURADORA=CAMINHO",
                    help="usa um relatório já baixado em vez de acessar o portal")
    args = ap.parse_args(argv)

    arq_log = configurar_log()
    arquivos_manuais = {}
    for item in args.arquivo:
        nome, _, caminho = item.partition("=")
        arquivos_manuais[nome.strip().lower()] = Path(caminho.strip())

    escolhidas = [s.lower() for s in args.seguradoras] or list(arquivos_manuais) or list(SEGURADORAS)
    desconhecidas = [s for s in escolhidas if s not in SEGURADORAS]
    if desconhecidas:
        log.error("Seguradora desconhecida: %s (opções: %s)", desconhecidas, list(SEGURADORAS))
        return 2

    dados, status = [], []
    precisa_navegador = any(s not in arquivos_manuais for s in escolhidas)
    pw = navegador = None
    if precisa_navegador:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        navegador = pw.chromium.launch(headless=config.NAVEGADOR_OCULTO)

    try:
        for chave in escolhidas:
            seg = SEGURADORAS[chave]()
            log.info("=== %s ===", seg.nome)
            try:
                if chave in arquivos_manuais:
                    arquivo = arquivos_manuais[chave]
                else:
                    contexto = navegador.new_context(accept_downloads=True, locale="pt-BR",
                                                     viewport={"width": 1366, "height": 900})
                    page = contexto.new_page()
                    try:
                        arquivo = seg.baixar(page)
                    except Exception:
                        foto = config.PASTA_LOGS / f"erro_{chave}_{datetime.now():%Y%m%d_%H%M%S}.png"
                        try:
                            page.screenshot(path=str(foto), full_page=True)
                            log.error("Print da tela no momento do erro: %s", foto)
                        except Exception:
                            pass
                        raise
                    finally:
                        contexto.close()
                log.info("Relatório: %s", arquivo)
                df = seg.normalizar(arquivo)
                dados.append(df)
                status.append({"seguradora": seg.nome, "situacao": "OK",
                               "detalhe": Path(arquivo).name})
                log.info("%d parcelas em aberto", len(df))
            except Exception as e:
                log.exception("Falha na %s", seg.nome)
                status.append({"seguradora": seg.nome, "situacao": "ERRO", "detalhe": str(e)[:300]})
    finally:
        if navegador:
            navegador.close()
        if pw:
            pw.stop()

    destino = config.PASTA_SAIDAS / f"CONTROLE_INADIMPLENCIA_{datetime.now():%Y-%m-%d}.xlsx"
    gerar_planilha(dados, status, destino)
    log.info("Planilha consolidada: %s", destino)
    log.info("Log desta execução: %s", arq_log)
    return 0 if all(s["situacao"] == "OK" for s in status) else 1


if __name__ == "__main__":
    sys.exit(main())
