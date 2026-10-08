import importlib
import sys
import types


def _carregar_bot():
    automia = types.ModuleType("automia")
    automia.Automia = type("Automia", (), {})
    automia.TaskFinishStatus = types.SimpleNamespace(SUCCESS="success", FAILED="failed")
    sys.modules["automia"] = automia
    sys.modules.pop("bot", None)
    return importlib.import_module("bot")


def test_parametros_ausentes_usam_defaults():
    bot = _carregar_bot()

    assert bot._parametros(types.SimpleNamespace(parameters=None)) == {}
    assert bot._filas({}) == ["validador"]


def test_filas_aceita_string_ou_lista():
    bot = _carregar_bot()

    assert bot._filas({"filas": "validador, transmissor"}) == ["validador", "transmissor"]
    assert bot._filas({"filas": ["validador"]}) == ["validador"]


def test_max_itens_padrao_um_e_aceita_texto():
    bot = _carregar_bot()

    assert bot._max_itens({}) == 1
    assert bot._max_itens({"max_itens": "300"}) == 300
    for invalido in (0, -1, "abc", True, 2.5):
        try:
            bot._max_itens({"max_itens": invalido})
        except ValueError:
            continue
        raise AssertionError(f"max_itens={invalido!r} deveria ser recusado")


def test_main_finaliza_sucesso_com_output():
    bot = _carregar_bot()
    chamadas = []

    class FakeBot:
        def get_execution(self):
            return types.SimpleNamespace(parameters={"filas": ["validador"]})

        def log(self, mensagem):
            chamadas.append(("log", mensagem))

        def error(self, erro, mensagem):
            chamadas.append(("error", erro, mensagem))

        def finish_task(self, status, mensagem, output=None):
            chamadas.append(("finish", status, mensagem, output))

    bot.Automia.from_runner = staticmethod(lambda: FakeBot())
    bot.executar_uma_vez = lambda filas, max_itens: {"status": "processed", "queue": filas[0]}

    bot.main()

    assert [chamada[0] for chamada in chamadas] == ["log", "finish"]
    assert chamadas[-1][1] == "success"
    assert chamadas[-1][3] == {"status": "processed", "queue": "validador"}


def test_main_registra_e_finaliza_falha():
    bot = _carregar_bot()
    chamadas = []

    class FakeBot:
        def get_execution(self):
            return types.SimpleNamespace(parameters={"filas": []})

        def log(self, mensagem):
            chamadas.append(("log", mensagem))

        def error(self, erro, mensagem):
            chamadas.append(("error", erro, mensagem))

        def finish_task(self, status, mensagem, output=None):
            chamadas.append(("finish", status, mensagem, output))

    bot.Automia.from_runner = staticmethod(lambda: FakeBot())
    bot.main()

    assert chamadas[0][0] == "error"
    assert chamadas[1][0] == "finish"
    assert chamadas[1][1] == "failed"
