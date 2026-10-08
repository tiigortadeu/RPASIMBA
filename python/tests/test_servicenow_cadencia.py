"""Limite de requisições por minuto do usuário de integração (bloqueio acima de 100/min)."""
import threading
import time

import pytest

from simba import servicenow


@pytest.fixture
def intervalo_curto(monkeypatch: pytest.MonkeyPatch) -> float:
    intervalo = 0.05
    monkeypatch.setattr(servicenow, "_intervalo", intervalo)
    monkeypatch.setattr(servicenow, "_proxima", 0.0)
    return intervalo


def test_requisicoes_seguidas_respeitam_o_intervalo(intervalo_curto: float) -> None:
    inicio = time.monotonic()
    for _ in range(6):
        servicenow._cadenciar()

    assert time.monotonic() - inicio >= 5 * intervalo_curto


def test_intervalo_vale_para_todas_as_threads(intervalo_curto: float) -> None:
    # O heartbeat roda em outra thread e conta no mesmo limite: 6 chamadas em 2 threads ocupam 6 vagas.
    def chamar() -> None:
        for _ in range(3):
            servicenow._cadenciar()

    threads = [threading.Thread(target=chamar) for _ in range(2)]
    inicio = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert time.monotonic() - inicio >= 5 * intervalo_curto
