from types import SimpleNamespace

import pytest

from simba import validacao
from simba.jab import ElementNotFound


class FakeEdit:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.focused = False

    def set_focus(self) -> None:
        self.focused = True

    def set_edit_text(self, value: str) -> None:
        self.value = value

    def get_value(self) -> str:
        return self.value


class FakeWindow:
    def __init__(self, edits: list[FakeEdit]) -> None:
        self.edits = edits

    def descendants(self, control_type: str) -> list[FakeEdit]:
        assert control_type == "Edit"
        return self.edits


def test_preencher_pasta_via_uia_confirma_valor(monkeypatch: pytest.MonkeyPatch) -> None:
    edit = FakeEdit()
    monkeypatch.setattr(validacao, "Desktop", lambda backend: SimpleNamespace(window=lambda handle: FakeWindow([edit])))

    assert validacao._preencher_pasta_via_uia(123, r"C:\RPA_INPUT\caso") is True
    assert edit.value == r"C:\RPA_INPUT\caso"
    assert edit.focused


def test_preencher_pasta_via_uia_tenta_edicoes_seguintes(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenEdit(FakeEdit):
        def set_edit_text(self, value: str) -> None:
            raise RuntimeError("controle sem edição")

    primeiro = BrokenEdit()
    segundo = FakeEdit()
    monkeypatch.setattr(
        validacao,
        "Desktop",
        lambda backend: SimpleNamespace(window=lambda handle: FakeWindow([primeiro, segundo])),
    )

    assert validacao._preencher_pasta_via_uia(123, r"C:\RPA_INPUT\caso") is True
    assert segundo.value == r"C:\RPA_INPUT\caso"


def test_campo_pasta_jab_usa_fallback_sem_caminho_fixo() -> None:
    candidato = SimpleNamespace(role="text", states="editable,focusable")
    dialogo = SimpleNamespace(walk=lambda: [(0, candidato)])

    class App:
        def control(self, *args, **kwargs):
            raise ElementNotFound("caminho JAB não existe")

    assert validacao._campo_pasta_jab(App(), dialogo) is candidato


def test_campo_pasta_jab_retorna_none_sem_campo_editavel() -> None:
    dialogo = SimpleNamespace(
        walk=lambda: [(0, SimpleNamespace(role="label", states="", name="Nome da pasta:"))]
    )

    class App:
        def control(self, *args, **kwargs):
            raise ElementNotFound("caminho JAB não existe")

    assert validacao._campo_pasta_jab(App(), dialogo) is None
