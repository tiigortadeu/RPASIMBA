import pytest

from simba import navigation, screens
from simba.app import SimbaApp, StepFailed


@pytest.fixture
def passo1_limpo(simba: SimbaApp) -> SimbaApp:
    yield simba
    navigation.passo1_limpar(simba)


def test_preenche_passo1_e_le_de_volta(passo1_limpo: SimbaApp) -> None:
    passo1_limpo.run_step("passo1_preencher", lambda app: navigation.passo1_preencher(app, "002", "123456", "77"))

    assert navigation.passo1_ler(passo1_limpo) == {"destino": "002-PF", "caso": "123456", "dv": "77"}


def test_selecionar_destino_atualiza_orgao(passo1_limpo: SimbaApp) -> None:
    passo1_limpo.run_step("passo1_destino", lambda app: navigation.passo1_preencher(app, "001-MPF", "", ""))

    root = passo1_limpo.window(screens.PASSO_1)
    orgao = root.by_path("root pane[0].layered pane[1].panel[0].panel[3].label[3]")
    assert orgao.name != "Selecione um Computador Destino."


def test_destino_inexistente_falha_apos_retentativas(passo1_limpo: SimbaApp) -> None:
    with pytest.raises(StepFailed):
        passo1_limpo.run_step("destino_invalido", lambda app: navigation.passo1_preencher(app, "XXX", "1", "1"), retries=1)

    assert passo1_limpo.is_alive()
