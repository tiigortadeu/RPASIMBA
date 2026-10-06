"""Simba Transmissor: seleciona o atendimento gerado pelo Validador, carrega o arquivo de chaves e envia ao órgão."""
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from simba import config, screens
from simba.app import RECOVERABLE, SimbaApp, SimbaAviso
from simba.jab import Element, ElementNotFound, wait_for

log = logging.getLogger(__name__)

TX = screens.TRANSMISSOR

VALIDADO = "já foram validados"
JA_ENVIADO = "já foram enviados anteriormente"
SUCESSO = "transferidos com sucesso"


class TransmissaoIncerta(Exception):
    """Falha depois do Enviar: o atendimento pode ter sido enviado. Fora de RECOVERABLE para não reenviar."""


@dataclass
class ResultadoTransmissao:
    mensagem: str
    pasta: Path
    comprovante: Optional[Path]


def _habilitado(element: Element) -> bool:
    return "enabled" in element.refresh().states.split(",")


def selecionar_atendimento(app: SimbaApp, atendimento: str) -> str:
    """Seleciona o atendimento pelo texto exato e devolve a situação exibida pelo Transmissor.

    Recusa (SimbaAviso) atendimento ausente da lista, não validado ou já enviado: reenvio só a pedido do órgão.
    """
    lista = app.control(TX, "Atendimentos")

    def item() -> Optional[int]:
        # Cada item é um painel com o nome do atendimento num label.
        nomes = [next((e.name for _, e in i.walk() if e.role == "label"), "") for i in lista.refresh().children()]
        return nomes.index(atendimento) + 1 if atendimento in nomes else None

    try:
        # +1 porque wait_for não aceita 0 como resultado.
        indice = wait_for(item, 3, f"atendimento {atendimento} na lista do Transmissor") - 1
    except ElementNotFound:
        raise SimbaAviso(f"Atendimento {atendimento} não está disponível no Transmissor")
    lista.select_child(indice)

    informacao = app.control(TX, "Informação")
    situacao = wait_for(
        lambda: (t := informacao.get_text()).startswith(atendimento) and t, 5, f"situação de {atendimento}"
    )
    if JA_ENVIADO in situacao or VALIDADO not in situacao:
        raise SimbaAviso(situacao.strip())
    return situacao.strip()


def carregar_chave(app: SimbaApp, chave: Path, senha: str) -> None:
    """Selecionar... -> arquivo de chaves -> senha. Chave inexistente, inválida ou senha errada viram SimbaAviso."""
    botao = app.control(TX, "Selecionar chave")
    wait_for(lambda: _habilitado(botao), 5, "habilitar Selecionar...")
    botao.press()
    app.expect(screens.ABRIR_CHAVE)
    app.control(screens.ABRIR_CHAVE, "Arquivo").set_text(str(chave))
    app.control(screens.ABRIR_CHAVE, "Abrir").press()

    def senha_pedida() -> Optional[bool]:
        # Arquivo inexistente: o Transmissor responde com "Informação" (não com Aviso/Erro).
        if app.is_open(screens.INFORMACAO):
            mensagem = app.window_text(screens.INFORMACAO)
            app.control(screens.INFORMACAO, "OK").click()
            raise SimbaAviso(mensagem)
        return app.is_open(screens.SENHA_CHAVE)

    app.expect_value(senha_pedida, config.SCREEN_TIMEOUT, "pedido de senha da chave")
    app.control(screens.SENHA_CHAVE, "Senha").set_text(senha)
    app.control(screens.SENHA_CHAVE, "OK").press()
    # Senha fora de 8-16 caracteres ou chave inválida abrem "Erro" (SimbaAviso via expect_value).
    enviar = app.control(TX, "Enviar")
    app.expect_value(lambda: _habilitado(enviar), config.SCREEN_TIMEOUT, "chave carregada (Enviar habilitado)")


def enviar(app: SimbaApp, pasta: Path) -> ResultadoTransmissao:
    """Enviar -> salva o comprovante em `pasta` -> mensagem de sucesso.

    Qualquer falha técnica depois do clique vira TransmissaoIncerta: o envio pode ter acontecido.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    app.control(TX, "Enviar").press()
    try:
        informacao = app.control(TX, "Informação")

        def concluido() -> Optional[str]:
            if app.is_open(screens.COMPROVANTE):
                app.control(screens.COMPROVANTE, "Pasta").set_text(str(pasta))
                app.control(screens.COMPROVANTE, "Selecionar Pasta").press()
                app.expect_closed(screens.COMPROVANTE)
            if app.is_open(screens.INFORMACAO):
                mensagem = app.window_text(screens.INFORMACAO)
                app.control(screens.INFORMACAO, "OK").click()
                return mensagem
            texto = informacao.get_text()
            return texto if SUCESSO in texto else None

        mensagem = app.expect_value(concluido, config.ENVIO_TIMEOUT, "conclusão do envio")
    except RECOVERABLE as err:
        raise TransmissaoIncerta(f"Falha depois do Enviar; confira se o atendimento foi enviado: {err}") from err
    pdfs = sorted(pasta.glob("*.pdf"), key=lambda p: p.stat().st_mtime)
    if not pdfs:
        log.warning("Comprovante não encontrado em %s", pasta)
    return ResultadoTransmissao(mensagem.strip(), pasta, pdfs[-1] if pdfs else None)


def arquivar_arquivos(atendimento: str, pasta_arquivos: Path, destino: Path) -> Path:
    """Grava em `destino` o zip <atendimento>_GABs.zip com os arquivos validados do atendimento."""
    destino.mkdir(parents=True, exist_ok=True)
    pacote = destino / f"{atendimento}_GABs.zip"
    with zipfile.ZipFile(pacote, "w", zipfile.ZIP_DEFLATED) as z:
        for arquivo in sorted(p for p in pasta_arquivos.iterdir() if p.is_file()):
            z.write(arquivo, arquivo.name)
    return pacote
