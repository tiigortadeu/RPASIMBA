"""Navegação mínima na Cabine CCS-JUD.

Abre (ou reutiliza) a Cabine, entra em Controle de Mensagens e seleciona
Requisição de Movimentação Financeira. Não seleciona nem envia requisições.

Uso:
    .venv\\Scripts\\python cabine_jd.py
    .venv\\Scripts\\python cabine_jd.py --dry-run
"""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import time
from ctypes import wintypes
from simba import config


EXECUTAVEL = config.CABINE_EXE
TITULO = "Cabine CCS-JUD"
TEMPO_ABERTURA = 60
# O menu lateral é customizado e não expõe o item na árvore UIA observada.
# Este é o único fallback posicional mantido; a aba interna é selecionada por UIA.
CONTROLE_MENSAGENS = (0.090, 0.250)

SW_RESTORE = 9
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
]


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _window_class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def localizar_janela(pid: int | None = None) -> int | None:
    candidatas: list[int] = []

    @EnumWindowsProc
    def callback(hwnd: int, _lparam: int) -> bool:
        if _window_title(hwnd) != TITULO:
            return True
        if pid is not None:
            janela_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(janela_pid))
            if janela_pid.value != pid:
                return True
        candidatas.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    if not candidatas:
        return None

    candidatas.sort(key=lambda item: _window_class(item) == "TfrmPrincipalCCS_JUD", reverse=True)
    for hwnd in candidatas:
        rect = RECT()
        valido = user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if user32.IsWindowVisible(hwnd) and valido and rect.right > rect.left and rect.bottom > rect.top:
            return hwnd
    return candidatas[0]


def abrir_ou_reutilizar() -> int:
    hwnd = localizar_janela()
    pid: int | None = None
    if hwnd is None:
        if EXECUTAVEL is None:
            raise FileNotFoundError("Defina CABINE_EXE no .env com o caminho do executável da Cabine")
        if not EXECUTAVEL.is_file():
            raise FileNotFoundError(f"Executável da Cabine não encontrado: {EXECUTAVEL}")
        processo = subprocess.Popen([str(EXECUTAVEL)], cwd=str(EXECUTAVEL.parent))
        pid = processo.pid
        limite = time.monotonic() + TEMPO_ABERTURA
        while hwnd is None and time.monotonic() < limite:
            time.sleep(0.15)
            hwnd = localizar_janela(pid)
    if hwnd is None:
        raise TimeoutError(f"Janela {TITULO!r} não apareceu em {TEMPO_ABERTURA}s")

    rect = RECT()
    valido = user32.GetWindowRect(hwnd, ctypes.byref(rect)) and rect.right > rect.left and rect.bottom > rect.top
    if not user32.IsWindowVisible(hwnd) or not valido:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)

    limite = time.monotonic() + 10
    while time.monotonic() < limite:
        atualizado = localizar_janela(pid)
        if atualizado is None and pid is None:
            atualizado = localizar_janela()
        if atualizado is not None:
            rect = RECT()
            valido = user32.GetWindowRect(atualizado, ctypes.byref(rect))
            if valido and rect.right > rect.left and rect.bottom > rect.top:
                user32.SetForegroundWindow(atualizado)
                garantir_tela_cheia(atualizado)
                return atualizado
        time.sleep(0.1)
    raise TimeoutError(f"Janela {TITULO!r} não ficou visível após restauração")


def garantir_tela_cheia(hwnd: int) -> None:
    """Reinicia o estado visual para maximizar a área útil da Cabine."""
    user32.SetForegroundWindow(hwnd)
    if not user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
    user32.SetForegroundWindow(hwnd)

    limite = time.monotonic() + 10
    while time.monotonic() < limite:
        rect = RECT()
        visivel = user32.IsWindowVisible(hwnd)
        valido = user32.GetWindowRect(hwnd, ctypes.byref(rect))
        maximizada = bool(user32.IsZoomed(hwnd))
        if visivel and valido and maximizada and rect.right > rect.left and rect.bottom > rect.top:
            return
        time.sleep(0.1)
    raise TimeoutError(f"Janela {TITULO!r} não ficou maximizada")


def ponto_normalizado(hwnd: int, proporcao: tuple[float, float]) -> tuple[int, int]:
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    escala = user32.GetDpiForWindow(hwnd) / 96 if user32.GetDpiForWindow(hwnd) else 1
    left = round(rect.left * escala)
    top = round(rect.top * escala)
    largura = round((rect.right - rect.left) * escala)
    altura = round((rect.bottom - rect.top) * escala)
    if largura <= 0 or altura <= 0:
        raise RuntimeError(f"Janela {TITULO!r} sem área visível: {largura}x{altura}")
    return (
        left + round(largura * proporcao[0]),
        top + round(altura * proporcao[1]),
    )


def clicar(hwnd: int, proporcao: tuple[float, float], dry_run: bool) -> tuple[int, int]:
    ponto = ponto_normalizado(hwnd, proporcao)
    if not dry_run:
        user32.SetCursorPos(*ponto)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    return ponto


def navegar(dry_run: bool = False) -> int:
    hwnd = abrir_ou_reutilizar()
    from cabine_ui import CabineUIDriver

    driver = CabineUIDriver(hwnd)
    if driver.tem_resposta_aberta():
        print("execução: janela de resposta já aberta; navegação reutilizada")
        return hwnd

    primeiro = clicar(hwnd, CONTROLE_MENSAGENS, dry_run)
    if not dry_run:
        driver.selecionar_requisicao()
        segundo = "UIA"
    else:
        segundo = "não executada"
    modo = "simulação" if dry_run else "execução"
    print(f"{modo}: Controle de Mensagens={primeiro}; "
          f"Requisição de Movimentação Financeira={segundo}")
    return hwnd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="abre/ativa a janela e mostra os pontos, sem clicar",
    )
    args = parser.parse_args()
    navegar(args.dry_run)


if __name__ == "__main__":
    main()
