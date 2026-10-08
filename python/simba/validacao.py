"""Passo 2: validação dos arquivos de um atendimento já gravado (CC 3454 para Banco, GAB para Corretora)."""
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import win32con
import win32clipboard
import win32api
import win32gui
from pywinauto import Desktop
from pywinauto.findwindows import ElementNotFoundError

from simba import config, screens
from simba.app import SimbaApp, SimbaAviso, tentar_trazer_para_frente
from simba.jab import Element, ElementNotFound, wait_for

P2 = screens.PASSO_2
log = logging.getLogger(__name__)

# Botão do Passo 1 conforme o campo `Tipo` do work item (variável GabOr3454 no .iBot).
BOTAO_POR_TIPO = {
    "Banco": "Validar Arquivos CC 3454",
    "Corretora": "Validar Arquivos GAB",
}

FIM_DA_VERIFICACAO = "Fim da verificação."
# Frases que o .iBot tratava como reprovação.
ERROS_CONHECIDOS = ("erro no arquivo", "não encontrado")


class ArquivosReprovados(SimbaAviso):
    """O Simba terminou a verificação e reprovou os arquivos. Não há nova tentativa."""


@dataclass
class ResultadoValidacao:
    aprovado: bool
    mensagens: str


def selecionar_atendimento(app: SimbaApp, atendimento: str) -> None:
    lista = app.control(screens.PASSO_1, "Atendimento a Validar")
    itens = [e.name for _, e in lista.walk() if e is not lista]
    if atendimento not in itens:
        raise SimbaAviso(f"Atendimento {atendimento} não está cadastrado no Simba")
    lista.select_child(itens.index(atendimento))


def abrir_passo2(app: SimbaApp, atendimento: str, tipo: str) -> None:
    if tipo not in BOTAO_POR_TIPO:
        raise ValueError(f"Tipo inválido: {tipo!r} (esperado {' ou '.join(BOTAO_POR_TIPO)})")
    selecionar_atendimento(app, atendimento)
    botao = app.control(screens.PASSO_1, BOTAO_POR_TIPO[tipo])
    # Os botões de validação só habilitam depois que um atendimento é selecionado.
    try:
        wait_for(lambda: "enabled" in botao.refresh().states.split(","), 5, f"habilitar {BOTAO_POR_TIPO[tipo]}")
    except ElementNotFound:
        # O Simba libera o leiaute conforme o órgão de destino (ex.: 056-PCPR e 041-TST só aceitam CC 3454 mesmo
        # para corretora). Com outro botão de validação habilitado, repetir não resolve.
        habilitados = [
            nome
            for nome in BOTAO_POR_TIPO.values()
            if "enabled" in app.control(screens.PASSO_1, nome).refresh().states.split(",")
        ]
        if not habilitados:
            raise
        raise SimbaAviso(
            f"O Simba não libera '{BOTAO_POR_TIPO[tipo]}' para o atendimento {atendimento} (Tipo {tipo}); "
            f"para este órgão de destino só habilita: {', '.join(habilitados)}. Confira o Tipo do caso e o "
            f"leiaute dos arquivos."
        ) from None
    botao.press()
    app.expect(P2)
    exibido = app.control(P2, "Atendimento").name
    if exibido != atendimento:
        raise AssertionError(f"Passo 2 abriu para {exibido!r}, esperado {atendimento!r}")


def selecionar_pasta(app: SimbaApp, pasta: Path) -> None:
    app.control(P2, "Selecionar Pasta").press()
    app.expect(screens.DIRETORIO)
    dialogo = app.window(screens.DIRETORIO)
    caminho = str(pasta)
    campo = _campo_pasta_jab(app, dialogo)
    # set_text pelo JAB não depende do foco da janela: funciona com o runner em segundo plano (play do console).
    if campo is not None and _preencher_pasta_via_jab(campo, caminho):
        log.debug("Campo de pasta preenchido via JAB: %s", caminho)
    elif _preencher_pasta_via_uia(dialogo.hwnd, caminho):
        log.debug("Campo de pasta preenchido via UI Automation: %s", caminho)
    elif campo is not None:
        _colar_pasta_no_dialogo(campo, caminho)
        log.debug("Campo de pasta preenchido via JAB/clipboard: %s", caminho)
    else:
        raise RuntimeError(f"Não foi possível localizar o campo de pasta: {pasta}")

    _confirmar_pasta(dialogo.hwnd, app)
    try:
        app.expect_closed(screens.DIRETORIO, timeout=2)
    except ElementNotFound:
        if not win32gui.IsWindow(dialogo.hwnd):
            raise
        _confirmar_pasta(dialogo.hwnd, app)
        app.expect_closed(screens.DIRETORIO)
    wait_for(
        lambda: app.control(P2, "Pasta selecionada").get_text().strip() == caminho,
        5,
        "atualização da pasta selecionada",
    )


def _campo_pasta_jab(app: SimbaApp, dialogo: Element) -> Optional[Element]:
    """Localiza o campo editável mesmo quando o caminho JAB varia entre servidores."""
    try:
        return app.control(screens.DIRETORIO, "Pasta", timeout=1)
    except ElementNotFound:
        pass
    candidatos = [
        elemento
        for _, elemento in dialogo.walk()
        if elemento.role == "text" and "editable" in elemento.states.split(",")
    ]
    if len(candidatos) == 1:
        return candidatos[0]
    if candidatos:
        return candidatos[-1]
    return None


def _confirmar_pasta(hwnd: int, app: SimbaApp) -> None:
    """Confirma pelo botão UIA quando disponível, com fallback para JAB/Enter."""
    try:
        janela = Desktop(backend="uia").window(handle=hwnd)
        botoes = janela.descendants(control_type="Button")
        for botao in botoes:
            if botao.window_text().strip().lower() == "selecionar pasta":
                botao.click_input()
                return
    except (ElementNotFoundError, RuntimeError):
        pass
    try:
        app.control(screens.DIRETORIO, "Selecionar Pasta", timeout=1).press()
    except ElementNotFound:
        _pressionar_enter(hwnd)


def _preencher_pasta_via_jab(campo: Element, pasta: str) -> bool:
    campo.set_text(pasta)
    return campo.refresh().get_text().strip() == pasta


def _preencher_pasta_via_uia(hwnd: int, pasta: str) -> bool:
    try:
        janela = Desktop(backend="uia").window(handle=hwnd)
        edicoes = janela.descendants(control_type="Edit")
    except (ElementNotFoundError, RuntimeError):
        return False
    if not edicoes:
        return False
    for edicao in edicoes:
        try:
            edicao.set_focus()
            edicao.set_edit_text(pasta)
            try:
                return str(edicao.get_value()).strip() == pasta
            except AttributeError:
                return edicao.window_text().strip() == pasta
        except (ElementNotFoundError, RuntimeError, AttributeError):
            continue
    return False


def _colar_pasta_no_dialogo(campo, pasta: str) -> None:
    """Contorna versões do JAB que aceitam set_text, mas não atualizam o campo Java."""
    win32gui.SetForegroundWindow(campo.hwnd)
    info = campo.info
    x, y, width, height = (int(info.x), int(info.y), int(info.width), int(info.height))
    if width > 0 and height > 0:
        win32api.SetCursorPos((x + width // 2, y + height // 2))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, pasta)
    finally:
        win32clipboard.CloseClipboard()
    campo._bridge.jab.request_focus(campo.context)
    wait_for(lambda: "focused" in campo.refresh().states.split(","), 2, "foco no campo de pasta")
    time.sleep(0.2)
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(ord("A"), 0, 0, 0)
    win32api.keybd_event(ord("A"), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(ord("V"), 0, 0, 0)
    win32api.keybd_event(ord("V"), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)


def _pressionar_enter(hwnd: int) -> None:
    if not win32gui.IsWindow(hwnd):
        raise RuntimeError(f"Janela de seleção de pasta inválida: hwnd={hwnd}")
    tentar_trazer_para_frente(hwnd)
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0xC0000001)


def aguardar_verificacao(app: SimbaApp, timeout: float = config.VALIDACAO_TIMEOUT) -> ResultadoValidacao:
    mensagens = app.control(P2, "Mensagens")

    def terminou() -> Optional[str]:
        texto = mensagens.get_text()
        return texto if FIM_DA_VERIFICACAO in texto else None

    texto = wait_for(terminou, timeout, "fim da verificação dos arquivos")
    continuar = app.control(P2, "Continuar").refresh()
    aprovado = "enabled" in continuar.states.split(",") and not any(e in texto.lower() for e in ERROS_CONHECIDOS)
    return ResultadoValidacao(aprovado, texto.strip())


def validar_arquivos(app: SimbaApp, atendimento: str, tipo: str, pasta: Path) -> ResultadoValidacao:
    """Passo 1 -> Passo 2 -> seleciona a pasta -> espera o fim da verificação.

    Arquivos reprovados viram ArquivosReprovados com as Mensagens do Simba (o errorHandling do .iBot),
    depois de voltar ao Passo 1. Em caso de aprovação, a tela Passo 2 fica aberta com Continuar habilitado.
    """
    if not pasta.is_dir():
        raise FileNotFoundError(f"Pasta de arquivos não existe: {pasta}")
    abrir_passo2(app, atendimento, tipo)
    selecionar_pasta(app, pasta)
    resultado = aguardar_verificacao(app)
    if not resultado.aprovado:
        # Volta ao Passo 1 para o próximo item não precisar reiniciar o Simba.
        app.control(P2, "Voltar").press()
        app.window(screens.PASSO_1)
        raise ArquivosReprovados(_so_reprovacoes(resultado.mensagens))
    return resultado


# Linhas das Mensagens do Passo 2 que não explicam a reprovação.
_LINHAS_INFORMATIVAS = ("validado com êxito", "Relatório de inconsistências gerado", FIM_DA_VERIFICACAO)


def _so_reprovacoes(mensagens: str) -> str:
    """Mensagens do Simba sem as linhas de sucesso/informativas, para o erro ir direto ao ponto."""
    linhas = [l for l in mensagens.splitlines() if l.strip() and not any(i in l for i in _LINHAS_INFORMATIVAS)]
    return "\n".join(linhas) or mensagens
