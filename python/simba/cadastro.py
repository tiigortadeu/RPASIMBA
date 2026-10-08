"""Cadastro de um atendimento: Passo 1 -> Dados do Caso -> Investigados.

A entrada é o mesmo JSON do work item usado pelo Simba Validador.iBot.
"""
import re
from dataclasses import dataclass, field
from typing import Any

import win32con
import win32gui

from simba import navigation, screens
from simba.app import SimbaApp, tentar_trazer_para_frente

DC = screens.DADOS_DO_CASO
INV = screens.INVESTIGADO

# Campo da tela Dados do Caso -> atributo de Caso.
CAMPOS_DADOS_DO_CASO = {
    "Número da Instituição": "codigo",
    "Nome da instituição": "banco",
    "CNPJ da instituição": "cnpj",
    "Nome do responsável": "responsavel",
    "Telefone do responsável": "telefone",
    "Email do responsável": "email",
    "Número Bacen/SISBAJUD": "sisbajud",
    "Número do Ofício": "oficio",
    "Data atual": "data",
    "Número do Processo": "processo",
    "Número da Vara": "vara",
    "Nome do Tribunal": "tribunal",
    "Nome do Magistrado": "magistrado",
    "Cargo do Magistrado": "cargo",
    "Início do afastamento": "inicio",
    "Fim do afastamento": "fim",
    "Descrição do afastamento": "descricao",
}


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


@dataclass
class Investigado:
    tipo: str  # "PF" ou "PJ"
    documento: str
    nome: str
    info: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Investigado":
        tipo = str(data["Investigado_Type"]).upper()
        if tipo not in ("PF", "PJ"):
            raise ValueError(f"Investigado_Type inválido: {tipo!r} (esperado PF ou PJ)")
        return cls(tipo, _digits(str(data["Investigado_ID"])), data["Investigado_Nome"], data.get("Investigado_Info") or "")


@dataclass
class Caso:
    destino: str
    caso: str
    dv: str
    codigo: str
    banco: str
    cnpj: str
    responsavel: str
    telefone: str
    email: str
    data: str
    processo: str
    vara: str
    tribunal: str
    magistrado: str
    cargo: str
    inicio: str
    fim: str
    sisbajud: str = ""
    oficio: str = ""
    descricao: str = ""
    tipo: str = ""  # "Banco" (CC 3454) ou "Corretora" (GAB); define a validação do Passo 2
    investigados: list[Investigado] = field(default_factory=list)

    @property
    def pasta(self) -> str:
        """Nome do atendimento no Simba, igual ao `Folder` do .iBot."""
        return f"{self.destino}-{self.caso}-{self.dv}"

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Caso":
        return cls(
            destino=data["Destino"],
            caso=data["Caso"],
            dv=data["DV"],
            codigo=data["Código"],
            banco=data["Banco"],
            cnpj=data["CNPJ"],
            responsavel=data["Responsável"],
            telefone=data["Telefone"],
            email=data["Email"],
            data=data["Data"],
            processo=data["Processo"],
            vara=data["Vara"],
            tribunal=data["Tribunal"],
            magistrado=data["Magistrado"],
            cargo=data["Cargo"],
            inicio=data["Início"],
            fim=data["Fim"],
            # Não eram lidos pelo .iBot (os campos ficavam vazios).
            sisbajud=data.get("Sisbajud") or "",
            oficio=data.get("Ofício") or "",
            descricao=data.get("Descrição") or "",
            tipo=data.get("Tipo") or "",
            investigados=[Investigado.from_json(i) for i in data.get("Investigados") or []],
        )


def abrir_caso(app: SimbaApp, caso: Caso) -> None:
    """Passo 1: preenche e cadastra. Um DV inválido vira SimbaAviso com a mensagem do Simba."""
    navigation.passo1_preencher(app, caso.destino, caso.caso, caso.dv)
    app.control(screens.PASSO_1, "Cadastrar").press()
    app.expect(DC)


def preencher_dados_do_caso(app: SimbaApp, caso: Caso) -> None:
    for campo, atributo in CAMPOS_DADOS_DO_CASO.items():
        app.control(DC, campo).set_text(getattr(caso, atributo))


def adicionar_investigado(app: SimbaApp, investigado: Investigado) -> None:
    app.control(DC, "Abas").select_child(2)
    app.control(DC, "Adicionar Investigado").press()
    app.expect(INV)

    if investigado.tipo == "PF":
        app.control(INV, "Pessoa Física").click()
        app.control(INV, "CPF").set_text(investigado.documento)
    else:
        app.control(INV, "Pessoa Jurídica").click()
        app.control(INV, "CNPJ").set_text(investigado.documento)
    app.control(INV, "Nome").set_text(investigado.nome)
    app.control(INV, "Outras informações").set_text(investigado.info)

    # Mesma regra do .iBot: relacionamento Sim, com Conta Depósito e B/D/V marcados.
    app.control(INV, "Relacionamento Sim").click()
    for marcador in ("Conta Depósito", "B/D/V - Bens, Direitos ou Valores"):
        checkbox = app.control(INV, marcador)
        if not checkbox.checked:
            checkbox.click()

    app.control(INV, "Salvar").press()
    app.expect_closed(INV)


def investigados_na_tabela(app: SimbaApp) -> int:
    tabela = app.control(DC, "Tabela de Investigados")
    return app.bridge.jab.get_accessible_table_info(tabela.context).rowCount


def ler_dados_do_caso(app: SimbaApp) -> dict[str, str]:
    """Valores atuais dos campos de Dados do Caso, pelo nome do atributo de Caso."""
    return {atributo: app.control(DC, campo).get_text().strip() for campo, atributo in CAMPOS_DADOS_DO_CASO.items()}


def ler_investigados(app: SimbaApp) -> list[dict[str, str]]:
    """Linhas da tabela de investigados (colunas Tipo, CPF_CNPJ, Nome, Relac, Conta, B/D/V, Observacao, Inicio, Fim)."""
    tabela = app.control(DC, "Tabela de Investigados")
    jab = app.bridge.jab
    info = jab.get_accessible_table_info(tabela.context)
    colunas = ["Tipo", "CPF_CNPJ", "Nome", "Relac", "Conta", "B/D/V", "Observacao", "Inicio", "Fim"]
    linhas = []
    for r in range(info.rowCount):
        valores = []
        for c in range(info.columnCount):
            cell = jab.get_accessible_table_cell_info(info.accessibleTable, r, c)
            valores.append(jab.get_context_info(cell.accessibleContext).name)
        linhas.append(dict(zip(colunas, valores)))
    return linhas


def preencher_caso(app: SimbaApp, caso: Caso) -> None:
    """Passo 1 + Dados do Caso + investigados, sem gravar."""
    abrir_caso(app, caso)
    preencher_dados_do_caso(app, caso)
    for investigado in caso.investigados:
        adicionar_investigado(app, investigado)
    linhas = investigados_na_tabela(app)
    if linhas != len(caso.investigados):
        raise AssertionError(f"Tabela de investigados tem {linhas} linha(s), esperado {len(caso.investigados)}")


def gravar(app: SimbaApp) -> str:
    """Gravar -> confirma -> retorna a mensagem da janela Informação."""
    app.control(DC, "Gravar").press()
    app.expect(screens.ATENCAO)
    pergunta = app.window_text(screens.ATENCAO)
    if pergunta != "Confirma gravação?":
        raise AssertionError(f"Confirmação inesperada ao gravar: {pergunta!r}")

    dialogo = app.window(screens.ATENCAO)
    botao_sim = next(
        (
            elemento
            for _, elemento in dialogo.walk()
            if elemento.name.strip().lower().lstrip("&") == "sim"
            and elemento.role in {"push button", "button"}
        ),
        None,
    )
    if botao_sim is not None:
        botao_sim.press()
    else:
        _confirmar_dialogo_com_enter(dialogo.hwnd)

    app.expect(screens.INFORMACAO)
    mensagem = app.window_text(screens.INFORMACAO)
    informacao = app.window(screens.INFORMACAO)
    botao_ok = next(
        (
            elemento
            for _, elemento in informacao.walk()
            if elemento.name.strip().lower().lstrip("&") == "ok"
            and elemento.role in {"push button", "button"}
        ),
        None,
    )
    if botao_ok is not None:
        botao_ok.press()
    else:
        _confirmar_dialogo_com_enter(informacao.hwnd)
    app.expect_closed(screens.INFORMACAO)
    return mensagem


def _confirmar_dialogo_com_enter(hwnd: int) -> None:
    """Confirma um diálogo Java quando o JAB não expõe seus botões acessíveis."""
    if not win32gui.IsWindow(hwnd):
        raise RuntimeError(f"Janela de confirmação inválida: hwnd={hwnd}")
    tentar_trazer_para_frente(hwnd)
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0xC0000001)
