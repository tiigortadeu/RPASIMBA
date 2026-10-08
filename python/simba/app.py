import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TypeVar

import psutil
import pywintypes
import win32api
import win32clipboard
import win32con
import win32gui
import win32process
from JABWrapper.jab_wrapper import APIException

from simba import config, screens
from simba.jab import Bridge, Element, ElementNotFound, wait_for
from simba.screens import Screen

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class Programa:
    nome: str
    exe: Path
    jar: str
    # Tela em que toda etapa começa (run_step/ensure_ready).
    inicial: Screen
    telas: tuple[Screen, ...]

    @property
    def titulos(self) -> set[str]:
        return {screen.title for screen in self.telas}


VALIDADOR = Programa("Simba Validador", config.SIMBA_EXE, "simba-validador.jar", screens.PASSO_1, tuple(screens.ALL))
TRANSMISSOR = Programa(
    "Simba Transmissor",
    config.TRANSMISSOR_EXE,
    "simba-transmissor.jar",
    screens.TRANSMISSOR,
    tuple(screens.ALL_TRANSMISSOR),
)


class UnexpectedWindow(Exception):
    pass


class AppNotRunning(Exception):
    pass


class StepFailed(Exception):
    pass


class SimbaAviso(Exception):
    """Validação de negócio do Simba (diálogo Aviso/Erro). Reiniciar não resolve: não há nova tentativa."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# pywintypes.error: chamadas Win32 recusadas (ex.: foco de janela) são falhas técnicas, com nova tentativa.
RECOVERABLE = (
    ElementNotFound, UnexpectedWindow, AppNotRunning, APIException, psutil.Error, OSError, pywintypes.error
)


def tentar_trazer_para_frente(hwnd: int) -> None:
    """Pede o foco para a janela antes de mandar teclas por PostMessage (que chegam mesmo sem foco).

    O Windows recusa o foco a processos em segundo plano (o runner disparado pelo console): segue sem ele.
    """
    try:
        win32gui.SetForegroundWindow(hwnd)
    except pywintypes.error:
        log.debug("Foco recusado para a janela %s; enviando a tecla mesmo assim", hwnd)


def colar_no_campo(campo: Element, texto: str) -> None:
    """Último recurso para campos que aceitam set_text pelo JAB sem atualizar o campo Java: clica no campo e cola
    (Ctrl+A, Ctrl+V). Depende do foco da janela, que o Windows pode recusar a um runner em segundo plano."""
    win32gui.SetForegroundWindow(campo.hwnd)
    info = campo.info
    x, y, largura, altura = int(info.x), int(info.y), int(info.width), int(info.height)
    if largura > 0 and altura > 0:
        win32api.SetCursorPos((x + largura // 2, y + altura // 2))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, texto)
    finally:
        win32clipboard.CloseClipboard()
    campo._bridge.jab.request_focus(campo.context)
    wait_for(lambda: "focused" in campo.refresh().states.split(","), 2, "foco no campo")
    time.sleep(0.2)
    for tecla in (ord("A"), ord("V")):
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(tecla, 0, 0, 0)
        win32api.keybd_event(tecla, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)


_OPCOES_DE_IDIOMA = ("-Duser.language=", "-Duser.country=", "-Duser.region=", "-Duser.variant=")


@dataclass
class StepTiming:
    step: str
    seconds: float
    attempts: int
    ok: bool


class SimbaApp:
    def __init__(self, programa: Programa = VALIDADOR, bridge: Optional[Bridge] = None) -> None:
        self.programa = programa
        self.bridge = bridge or Bridge.get()
        self.timings: list[StepTiming] = []

    # --- processo -------------------------------------------------------

    def processes(self) -> list[psutil.Process]:
        """Launcher (.exe) e a JVM que roda o .jar do programa."""
        found = []
        for proc in psutil.process_iter(["name", "cmdline"]):
            name = (proc.info["name"] or "").lower()
            cmdline = " ".join(proc.info["cmdline"] or []).lower()
            if name == self.programa.exe.name or (name.startswith("java") and self.programa.jar in cmdline):
                found.append(proc)
        return found

    def pids(self) -> set[int]:
        return {p.pid for p in self.processes()}

    def is_alive(self) -> bool:
        return any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in self.processes())

    def start(self) -> None:
        exe = self.programa.exe
        if not exe.is_file():
            raise FileNotFoundError(f"{self.programa.nome} não encontrado em {exe}")
        # O idioma do Java vem de quem inicia o programa (o bot pode rodar com outro usuário/ambiente) e muda os
        # títulos dos diálogos padrão ("Abrir"/"Open", "Erro"/"Error"). Com a opção repetida a JVM fica com a
        # primeira: as de idioma já presentes no ambiente saem e entram as de SIMBA_JAVA_OPCOES.
        herdadas = [o for o in os.environ.get("JAVA_TOOL_OPTIONS", "").split() if not o.startswith(_OPCOES_DE_IDIOMA)]
        opcoes = " ".join([*herdadas, config.SIMBA_JAVA_OPCOES])
        subprocess.Popen([str(exe)], cwd=str(exe.parent), env={**os.environ, "JAVA_TOOL_OPTIONS": opcoes})
        self.window(self.programa.inicial, timeout=config.STARTUP_TIMEOUT)

    def kill(self) -> None:
        """Fecha o programa pelas janelas (WM_CLOSE) e mata o que não sair em FECHAR_TIMEOUT.

        Matar a JVM de um programa tira o outro, se estiver aberto, do Java Access Bridge (o Validador some da
        árvore JAB quando o Transmissor é morto). Fechando pela janela isso não acontece.
        """
        procs = self.processes()
        if not procs:
            return
        pids = {p.pid for p in procs}

        def fechar(hwnd: int, _: None) -> None:
            if win32process.GetWindowThreadProcessId(hwnd)[1] in pids and win32gui.IsWindowVisible(hwnd):
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

        win32gui.EnumWindows(fechar, None)
        _, vivos = psutil.wait_procs(procs, timeout=config.FECHAR_TIMEOUT)
        for proc in vivos:
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(vivos, timeout=10)

    def restart(self) -> None:
        self.kill()
        self.start()

    def ensure_ready(self) -> None:
        """Garante o app aberto e na tela inicial; reinicia se estiver fechado ou travado."""
        if not self.is_alive():
            log.info("%s não está rodando; iniciando", self.programa.nome)
            self.start()
            return
        try:
            self.window(self.programa.inicial, timeout=2)
        except ElementNotFound:
            log.warning("Tela %s não responde; reiniciando o %s", self.programa.inicial.name, self.programa.nome)
            self.restart()

    # --- telas e controles ----------------------------------------------

    def _running_pids(self) -> set[int]:
        # Falha na hora se o Simba caiu, em vez de esperar o timeout da tela.
        pids = self.pids()
        if not pids:
            raise AppNotRunning(f"{self.programa.nome} não está rodando")
        return pids

    def _find_window(self, screen: Screen) -> Optional[Element]:
        """Raiz da tela, se estiver aberta e visível; confere o marcador quando o título não basta."""
        for w in self.bridge.windows(self._running_pids(), visible=True):
            if w.title != screen.title:
                continue
            root = self.bridge.root(w)
            if screen.marker is None:
                return root
            try:
                if root.by_path(screen.marker.path).name == screen.marker.label:
                    return root
            except ElementNotFound:
                pass
        return None

    def window(self, screen: Screen, timeout: float = config.SCREEN_TIMEOUT) -> Element:
        return wait_for(lambda: self._find_window(screen), timeout, f"tela {screen.name!r}")

    def control(self, screen: Screen, name: str, timeout: float = config.SCREEN_TIMEOUT) -> Element:
        spec = screen.controls[name]

        def resolve() -> Element:
            root = self._find_window(screen)
            if root is None:
                raise ElementNotFound(f"tela {screen.name!r} não está aberta")
            try:
                element = root.by_path(spec.path)
                if spec.label is None or element.name == spec.label:
                    return element
            except ElementNotFound:
                if spec.label is None:
                    raise
            return root.find(spec.role, spec.label)

        return wait_for(resolve, timeout, f"{screen.name} / {name}")

    def is_open(self, screen: Screen) -> bool:
        return self._find_window(screen) is not None

    def window_text(self, screen: Screen) -> str:
        """Textos (labels) da janela, ex.: a mensagem de um diálogo."""
        root = self.window(screen, timeout=2)
        return "\n".join(e.name for _, e in root.walk() if e.role == "label" and e.name)

    def check_aviso(self) -> None:
        """Se o Simba abriu um diálogo Aviso/Erro, lê a mensagem, fecha o diálogo e levanta SimbaAviso."""
        for dialog in screens.DIALOGOS_DE_VALIDACAO:
            if self.is_open(dialog):
                message = self.window_text(dialog)
                self.control(dialog, "OK").click()
                raise SimbaAviso(message)

    def expect(self, screen: Screen, timeout: float = config.SCREEN_TIMEOUT) -> Element:
        """Espera `screen` abrir; se o Simba responder com Aviso, falha na hora com a mensagem."""

        def resolve() -> Optional[Element]:
            self.check_aviso()
            return self._find_window(screen)

        return wait_for(resolve, timeout, f"tela {screen.name!r}")

    def expect_value(self, fn: Callable[[], Optional[T]], timeout: float, what: str) -> T:
        """Espera `fn` devolver um valor; se o Simba responder com Aviso, falha na hora com a mensagem."""

        def resolve() -> Optional[T]:
            self.check_aviso()
            return fn()

        return wait_for(resolve, timeout, what)

    def expect_closed(self, screen: Screen, timeout: float = config.SCREEN_TIMEOUT) -> None:
        """Espera `screen` fechar; se o Simba responder com Aviso, falha na hora com a mensagem."""

        def closed() -> bool:
            self.check_aviso()
            return not self.is_open(screen)

        wait_for(closed, timeout, f"fechar tela {screen.name!r}")

    def close_window(self, screen: Screen) -> None:
        for w in self.bridge.windows(self.pids()):
            if w.title == screen.title:
                win32gui.PostMessage(w.hwnd, win32con.WM_CLOSE, 0, 0)

    def unexpected_windows(self) -> list[str]:
        return [w.title for w in self.bridge.windows(self.pids(), visible=True) if w.title not in self.programa.titulos]

    # --- execução de etapas com recuperação -------------------------------

    def run_step(self, step: str, fn: Callable[["SimbaApp"], T], retries: int = config.STEP_RETRIES) -> T:
        """Executa `fn` a partir da tela inicial do programa. Em falha, reinicia o Simba e tenta de novo."""
        started = time.monotonic()
        for attempt in range(1, retries + 2):
            try:
                self.ensure_ready()
                result = fn(self)
                # O Fechar do Passo 3 encerra o Simba; aí não há janelas a conferir.
                if self.is_alive():
                    self.check_aviso()
                    unexpected = self.unexpected_windows()
                    if unexpected:
                        raise UnexpectedWindow(f"Janelas inesperadas: {unexpected}")
                self._record(step, started, attempt, ok=True)
                return result
            except SimbaAviso as aviso:
                log.warning("Etapa %r recusada pelo Simba: %s", step, aviso.message)
                self._record(step, started, attempt, ok=False)
                raise
            except RECOVERABLE as err:
                log.warning("Etapa %r falhou (tentativa %d): %s", step, attempt, err)
                if attempt > retries:
                    self._record(step, started, attempt, ok=False)
                    raise StepFailed(f"Etapa {step!r} falhou após {attempt} tentativas") from err
                # Mata aqui; o ensure_ready da próxima tentativa reabre (falha ao abrir também conta como tentativa).
                self.kill()

    def _record(self, step: str, started: float, attempts: int, ok: bool) -> None:
        timing = StepTiming(step, time.monotonic() - started, attempts, ok)
        self.timings.append(timing)
        log.info("Etapa %r: %.2fs em %d tentativa(s)", step, timing.seconds, attempts)
