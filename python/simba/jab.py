import ctypes
import os
import queue
import re
import threading
import time
from ctypes import byref, wintypes
from typing import Callable, Iterator, Optional, TypeVar

import win32con
import win32gui

from simba import config

os.environ.setdefault("RC_JAVA_ACCESS_BRIDGE_DLL", config.JAB_DLL)

from JABWrapper.jab_types import AccessibleActionsToDo, JavaObject  # noqa: E402
from JABWrapper.jab_wrapper import JavaAccessBridgeWrapper, JavaWindow  # noqa: E402

T = TypeVar("T")

_PATH_SEGMENT = re.compile(r"^(?P<role>.+)\[(?P<index>\d+)\]$")


class ElementNotFound(Exception):
    pass


def wait_for(fn: Callable[[], Optional[T]], timeout: float, what: str) -> T:
    """Chama `fn` até retornar algo diferente de None/False ou estourar o timeout."""
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    while True:
        try:
            result = fn()
            if result:
                return result
        except ElementNotFound as err:
            last_error = err
        if time.monotonic() >= deadline:
            raise ElementNotFound(f"Timeout ({timeout}s) aguardando {what}") from last_error
        time.sleep(config.POLL_INTERVAL)


class Element:
    def __init__(self, bridge: "Bridge", context: JavaObject, hwnd: int) -> None:
        self._bridge = bridge
        self.context = context
        self.hwnd = hwnd  # janela de topo que contém o elemento
        self.info = bridge.jab.get_context_info(context)

    @property
    def role(self) -> str:
        return self.info.role_en_US

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def states(self) -> str:
        return self.info.states_en_US

    def __repr__(self) -> str:
        return f"<{self.role} name={self.name!r} index={self.info.indexInParent}>"

    def children(self) -> Iterator["Element"]:
        for i in range(self.info.childrenCount):
            yield Element(self._bridge, self._bridge.jab.get_child_context(self.context, i), self.hwnd)

    def walk(self, depth: int = 0) -> Iterator[tuple[int, "Element"]]:
        yield depth, self
        for child in self.children():
            yield from child.walk(depth + 1)

    def by_path(self, path: str) -> "Element":
        """Resolve caminhos no formato do .iBot: 'root pane[0].layered pane[1].panel[0]...'.

        O índice é o indexInParent do controle, que costuma ser igual à posição do filho,
        mas não em abas (o painel da aba 2 é o filho 0 com indexInParent 2).
        """
        node = self
        for segment in path.split("."):
            match = _PATH_SEGMENT.match(segment)
            if not match:
                raise ValueError(f"Segmento de caminho inválido: {segment!r}")
            role, index = match["role"], int(match["index"])
            node = node._child_by_index(role, index, path)
        return node

    def _child_by_index(self, role: str, index: int, path: str) -> "Element":
        if index < self.info.childrenCount:
            child = Element(self._bridge, self._bridge.jab.get_child_context(self.context, index), self.hwnd)
            if child.role == role and child.info.indexInParent == index:
                return child
        for child in self.children():
            if child.role == role and child.info.indexInParent == index:
                return child
        raise ElementNotFound(f"{path}: {role}[{index}] não existe em {self}")

    def find(self, role: str, name: str) -> "Element":
        for _, element in self.walk():
            if element.role == role and element.name == name:
                return element
        raise ElementNotFound(f"{role} {name!r} não encontrado em {self}")

    def click(self) -> None:
        # Nomes de ação vêm no idioma da JVM ("clicar" em pt-BR).
        self._do_action({"click", "clicar"})

    def press(self) -> None:
        """Aciona o controle com foco + Espaço.

        Use em botões que abrem diálogo modal: a ação de clique do JAB fica bloqueada
        (~8s) até o modal fechar, e nesse intervalo o diálogo não pode ser lido.
        """
        self._bridge.jab.request_focus(self.context)
        # Só envia a tecla com o foco confirmado, senão o Espaço aciona outro controle.
        wait_for(lambda: "focused" in self.refresh().states.split(","), 2, f"foco em {self}")
        win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, win32con.VK_SPACE, 0)
        win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, win32con.VK_SPACE, 0xC0000001)

    @property
    def checked(self) -> bool:
        return "checked" in self.refresh().states.split(",")

    def select_child(self, index: int) -> None:
        """Seleciona o filho de índice `index` (ex.: aba de um page tab list)."""
        self._bridge.jab.add_accessible_selection_from_context(self.context, index)

    def _do_action(self, names: set[str]) -> None:
        actions = self._bridge.jab.get_accessible_actions(self.context)
        available = [actions.actionInfo[i].name for i in range(actions.actionsCount)]
        for i, name in enumerate(available):
            if name.lower() in names:
                todo = AccessibleActionsToDo(actionsCount=1, actions=(actions.actionInfo[i],))
                self._bridge.jab.do_accessible_actions(self.context, todo)
                return
        raise ElementNotFound(f"{self} não tem a ação {sorted(names)} (disponíveis: {available})")

    def set_text(self, text: str) -> None:
        self._bridge.jab.set_text_contents(self.context, text)

    def get_text(self) -> str:
        info = self._bridge.jab.get_context_text_info(self.context, 0, 0)
        if info.charCount == 0:
            return ""
        return self._bridge.jab.get_accessible_text_range(self.context, 0, info.charCount - 1, info.charCount + 1)

    def items(self) -> list[str]:
        """Itens de um combo box (lista do popup), na ordem de seleção."""
        return [e.name for _, e in self.walk() if e.role == "label"]

    def select_by_text(self, text: str) -> None:
        """Seleciona o item de um combo box pelo texto exato ou pelo código antes do '-' (ex.: '002' -> '002-PF')."""
        for index, item in enumerate(self.items()):
            if item == text or item.startswith(f"{text}-"):
                self._bridge.jab.add_accessible_selection_from_context(self.context, index)
                return
        raise ElementNotFound(f"Item {text!r} não existe em {self}")

    def selected_text(self) -> str:
        if self._bridge.jab.get_accessible_selection_count_from_context(self.context) == 0:
            return ""
        selected = self._bridge.jab.get_accessible_selection_from_context(self.context, 0)
        return Element(self._bridge, selected, self.hwnd).name

    def refresh(self) -> "Element":
        self.info = self._bridge.jab.get_context_info(self.context)
        return self


def _pump(pipe: "queue.Queue") -> None:
    try:
        jab = JavaAccessBridgeWrapper(ignore_callbacks=True)
    except Exception as err:
        pipe.put(err)
        return
    pipe.put(jab)
    user32 = ctypes.windll.user32
    message = wintypes.MSG()
    while user32.GetMessageW(byref(message), 0, 0, 0) > 0:
        user32.TranslateMessage(byref(message))
        user32.DispatchMessageW(byref(message))


class Bridge:
    """Sessão única do Java Access Bridge, com o message pump em thread própria."""

    _instance: Optional["Bridge"] = None

    def __init__(self) -> None:
        pipe: queue.Queue = queue.Queue()
        threading.Thread(target=_pump, args=(pipe,), daemon=True).start()
        result = pipe.get()
        if isinstance(result, Exception):
            raise result
        self.jab: JavaAccessBridgeWrapper = result

    @classmethod
    def get(cls) -> "Bridge":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def windows(self, pids: Optional[set[int]] = None, visible: bool = False) -> list[JavaWindow]:
        windows = self.jab.get_windows()
        return [
            w for w in windows
            if (pids is None or w.pid in pids) and (not visible or win32gui.IsWindowVisible(w.hwnd))
        ]

    def root(self, window: JavaWindow) -> Element:
        vm_id, context = self.jab.get_accessible_context_from_hwnd(window.hwnd)
        self.jab.set_hwnd(window.hwnd)
        self.jab.set_context(vm_id, context)
        return Element(self, context, window.hwnd)

    def window(self, title: str, pids: Optional[set[int]] = None) -> Optional[Element]:
        """Raiz da janela Java visível com o título exato, ou None.

        Só janelas visíveis contam: no startup o Passo 1 já existe (invisível) atrás do splash.
        """
        for w in self.windows(pids, visible=True):
            if w.title == title:
                return self.root(w)
        return None

    def wait_window(self, title: str, timeout: float, pids: Optional[set[int]] = None) -> Element:
        return wait_for(lambda: self.window(title, pids), timeout, f"janela {title!r}")
