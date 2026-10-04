"""Navegação na tela Passo 1. O cadastro de atendimentos fica em simba/cadastro.py."""
from simba import config, screens
from simba.app import SimbaApp
from simba.jab import wait_for


def passo1_preencher(app: SimbaApp, destino: str, caso: str, dv: str) -> None:
    combo = app.control(screens.PASSO_1, "Computador destino")
    # A lista de destinos carrega ~0.6s depois que a tela aparece.
    wait_for(combo.items, config.SCREEN_TIMEOUT, "lista de Computador destino")
    combo.select_by_text(destino)
    app.control(screens.PASSO_1, "Número do Caso").set_text(caso)
    app.control(screens.PASSO_1, "DV").set_text(dv)


def passo1_ler(app: SimbaApp) -> dict[str, str]:
    return {
        "destino": app.control(screens.PASSO_1, "Computador destino").selected_text(),
        "caso": app.control(screens.PASSO_1, "Número do Caso").get_text().strip(),
        "dv": app.control(screens.PASSO_1, "DV").get_text().strip(),
    }


def passo1_limpar(app: SimbaApp) -> None:
    app.control(screens.PASSO_1, "Número do Caso").set_text("")
    app.control(screens.PASSO_1, "DV").set_text("")

