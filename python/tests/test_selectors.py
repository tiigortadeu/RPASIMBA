import pytest

from simba import screens
from simba.app import SimbaApp


@pytest.mark.parametrize("name", list(screens.PASSO_1.controls))
def test_controle_passo1_encontrado(simba: SimbaApp, name: str) -> None:
    spec = screens.PASSO_1.controls[name]

    element = simba.control(screens.PASSO_1, name, timeout=2)

    assert element.role == spec.role
    if spec.label:
        assert element.name == spec.label
