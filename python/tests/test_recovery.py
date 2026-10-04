from simba import navigation, screens
from simba.app import SimbaApp


def test_reabre_quando_simba_foi_fechado(simba: SimbaApp) -> None:
    simba.kill()
    assert not simba.is_alive()

    simba.run_step("recuperar_fechado", lambda app: app.window(screens.PASSO_1))

    assert simba.is_alive()


def test_reinicia_e_repete_etapa_quando_app_cai_no_meio(simba: SimbaApp) -> None:
    tentativas = []

    def etapa(app: SimbaApp) -> dict[str, str]:
        tentativas.append(1)
        if len(tentativas) == 1:
            app.kill()  # simula o Simba caindo no meio da etapa
        navigation.passo1_preencher(app, "002", "654321", "11")
        return navigation.passo1_ler(app)

    lido = simba.run_step("recuperar_queda", etapa)

    assert len(tentativas) == 2
    assert lido == {"destino": "002-PF", "caso": "654321", "dv": "11"}
    navigation.passo1_limpar(simba)
