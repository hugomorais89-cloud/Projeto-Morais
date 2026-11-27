"""Configurações lidas do arquivo .env (na raiz do projeto)."""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
# override: o .env sempre vale (o painel repassa ao robô o ambiente carregado na abertura;
# sem isso, senhas trocadas depois de abrir o painel seriam ignoradas)
load_dotenv(RAIZ / ".env", override=True)

PASTA_DOWNLOADS = RAIZ / "downloads"
PASTA_SAIDAS = RAIZ / "saidas"
PASTA_LOGS = RAIZ / "logs"
PASTA_DADOS = RAIZ / "dados"

for _p in (PASTA_DOWNLOADS, PASTA_SAIDAS, PASTA_LOGS, PASTA_DADOS):
    _p.mkdir(exist_ok=True)

DIAS_RETROATIVOS = int(os.getenv("DIAS_RETROATIVOS", "90"))
NAVEGADOR_OCULTO = os.getenv("NAVEGADOR_OCULTO", "true").strip().lower() != "false"
# Opcional: caminho de um Chrome/Chromium já instalado (em branco = o do Playwright)
CHROMIUM_EXECUTAVEL = os.getenv("CHROMIUM_EXECUTAVEL", "").strip() or None


def credencial(prefixo: str) -> tuple[str, str]:
    """Retorna (usuario, senha) da seguradora, ex.: credencial('ALLIANZ')."""
    usuario = os.getenv(f"{prefixo}_USUARIO", "").strip()
    senha = os.getenv(f"{prefixo}_SENHA", "").strip()
    if not usuario or not senha:
        raise RuntimeError(
            f"Preencha {prefixo}_USUARIO e {prefixo}_SENHA no arquivo .env"
        )
    return usuario, senha


# Painel web
PAINEL_USUARIO = os.getenv("PAINEL_USUARIO", "morais").strip()
PAINEL_SENHA = os.getenv("PAINEL_SENHA", "").strip()
PAINEL_PORTA = int(os.getenv("PAINEL_PORTA", "8050"))
