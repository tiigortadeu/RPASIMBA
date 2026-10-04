"""Passo 2: validação dos arquivos de um atendimento já gravado (CC 3454 para Banco, GAB para Corretora)."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from simba import config, screens
from simba.app import SimbaApp, SimbaAviso
from simba.jab import wait_for

P2 = screens.PASSO_2

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
    wait_for(lambda: "enabled" in botao.refresh().states.split(","), 5, f"habilitar {BOTAO_POR_TIPO[tipo]}")
    botao.press()
    app.expect(P2)
    exibido = app.control(P2, "Atendimento").name
    if exibido != atendimento:
        raise AssertionError(f"Passo 2 abriu para {exibido!r}, esperado {atendimento!r}")


def selecionar_pasta(app: SimbaApp, pasta: Path) -> None:
    app.control(P2, "Selecionar Pasta").press()
    app.expect(screens.DIRETORIO)
    app.control(screens.DIRETORIO, "Pasta").set_text(str(pasta))
    app.control(screens.DIRETORIO, "Selecionar Pasta").press()
    app.expect_closed(screens.DIRETORIO)


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
        raise ArquivosReprovados(resultado.mensagens)
    return resultado
