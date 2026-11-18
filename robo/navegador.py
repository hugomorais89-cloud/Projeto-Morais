"""Funções de apoio para navegar em portais (inclusive telas dentro de iframes)."""
from __future__ import annotations

import time


def esperar_carregar(page, extra_ms: int = 1000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass
    page.wait_for_timeout(extra_ms)


def achar_todos(page, construir, tempo: float = 30, obrigatorio: bool = True):
    """Procura, na página e em todos os iframes, um Locator com algum item visível.

    `construir` recebe um frame e devolve um Locator, ex.:
        achar_todos(page, lambda f: f.get_by_text("Pesquisar"))
    Retorna o Locator inteiro (use .nth(i) para escolher).
    """
    limite = time.monotonic() + tempo
    while True:
        for frame in page.frames:
            try:
                loc = construir(frame)
                if any(loc.nth(i).is_visible() for i in range(loc.count())):
                    return loc
            except Exception:
                continue
        if time.monotonic() > limite:
            if obrigatorio:
                raise TimeoutError("Elemento não encontrado na tela")
            return None
        page.wait_for_timeout(500)


def achar(page, construir, tempo: float = 30, obrigatorio: bool = True):
    """Como achar_todos, mas devolve só o primeiro item visível."""
    loc = achar_todos(page, construir, tempo, obrigatorio)
    if loc is None:
        return None
    for i in range(loc.count()):
        if loc.nth(i).is_visible():
            return loc.nth(i)
    return loc.first


def clicar_texto(page, texto: str, exato: bool = False, papel: str | None = None,
                 tempo: float = 30) -> None:
    if papel:
        el = achar(page, lambda f: f.get_by_role(papel, name=texto, exact=exato), tempo)
    else:
        el = achar(page, lambda f: f.get_by_text(texto, exact=exato), tempo)
    el.click()
    page.wait_for_timeout(800)
