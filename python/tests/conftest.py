import pytest

from simba.app import SimbaApp

_apps: list[SimbaApp] = []


@pytest.fixture(scope="session")
def simba() -> SimbaApp:
    app = SimbaApp()
    app.restart()
    _apps.append(app)
    yield app
    app.kill()


def pytest_terminal_summary(terminalreporter) -> None:
    timings = [t for app in _apps for t in app.timings]
    if not timings:
        return
    terminalreporter.section("tempos por etapa")
    for t in timings:
        status = "ok" if t.ok else "FALHOU"
        terminalreporter.write_line(f"{t.step:<40} {t.seconds:6.2f}s  tentativas={t.attempts}  {status}")
