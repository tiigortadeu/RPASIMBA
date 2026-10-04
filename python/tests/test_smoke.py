import time

from simba import config, screens
from simba.app import SimbaApp


def test_abre_simba_e_mostra_passo1(simba: SimbaApp) -> None:
    simba.kill()
    started = time.monotonic()
    simba.start()
    elapsed = time.monotonic() - started

    assert simba.is_alive()
    assert simba.window(screens.PASSO_1, timeout=1).name == screens.PASSO_1.title
    assert elapsed < config.STARTUP_TIMEOUT
