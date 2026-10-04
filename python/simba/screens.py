"""Telas e controles do Simba Validador, extraídos do mapeamento do Simba Validador.iBot.

`path` é o caminho JAB (igual ao do .iBot). `label` é o nome acessível esperado:
quando existe, é conferido no caminho e usado como fallback de busca se o caminho mudar.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Control:
    role: str
    path: str
    label: Optional[str] = None


@dataclass(frozen=True)
class Screen:
    name: str
    title: str
    controls: dict[str, Control] = field(default_factory=dict)
    # Rótulo que identifica a tela quando o título não basta (Passo 2 e Passo 3 não têm título).
    marker: Optional[Control] = None


_P1 = "root pane[0].layered pane[1].panel[0]."
PASSO_1 = Screen(
    "Passo 1",
    "Validador Bancário - Passo 1",
    {
        "Computador destino": Control("combo box", _P1 + "panel[3].combo box[1]"),
        "Número do Caso": Control("text", _P1 + "panel[3].text[5]"),
        "DV": Control("text", _P1 + "panel[3].text[7]"),
        "Cadastrar": Control("push button", _P1 + "panel[3].push button[9]", "Cadastrar"),
        "Atendimento a Validar": Control("list", _P1 + "scroll pane[6].viewport[0].list[0]"),
        "Validar Arquivos CC 3454": Control("push button", _P1 + "push button[9]", "Validar Arquivos CC 3454"),
        "Validar Arquivos GAB": Control("push button", _P1 + "push button[10]", "Validar Arquivos GAB"),
    },
)

_DC = "root pane[0].layered pane[1].panel[0]."
_DC_INST = _DC + "page tab list[4].page tab[0].panel[0]."
_DC_PROC = _DC + "page tab list[4].page tab[1].panel[1]."
_DC_INV = _DC + "page tab list[4].page tab[2].panel[2]."
DADOS_DO_CASO = Screen(
    "Dados do Caso",
    "Validador Bancário - Dados do Caso",
    {
        "Abas": Control("page tab list", _DC + "page tab list[4]"),
        "Instituição Financeira": Control("page tab", _DC + "page tab list[4].page tab[0]", "Instituição Financeira"),
        "Processo/Inquérito": Control("page tab", _DC + "page tab list[4].page tab[1]", "Processo/Inquérito"),
        "Investigados": Control("page tab", _DC + "page tab list[4].page tab[2]", "Investigados"),
        "Número da Instituição": Control("text", _DC_INST + "panel[0].text[1]"),
        "Nome da instituição": Control("text", _DC_INST + "panel[0].text[3]"),
        "CNPJ da instituição": Control("text", _DC_INST + "panel[0].text[5]"),
        "Nome do responsável": Control("text", _DC_INST + "panel[1].text[1]"),
        "Telefone do responsável": Control("text", _DC_INST + "panel[1].text[3]"),
        "Email do responsável": Control("text", _DC_INST + "panel[1].text[5]"),
        "Número Bacen/SISBAJUD": Control("text", _DC_PROC + "text[1]"),
        "Número do Ofício": Control("text", _DC_PROC + "text[3]"),
        "Data atual": Control("text", _DC_PROC + "text[5]"),
        "Número do Processo": Control("text", _DC_PROC + "text[7]"),
        "Número da Vara": Control("text", _DC_PROC + "text[9]"),
        "Nome do Tribunal": Control("text", _DC_PROC + "text[11]"),
        "Nome do Magistrado": Control("text", _DC_PROC + "text[13]"),
        "Cargo do Magistrado": Control("text", _DC_PROC + "text[15]"),
        "Início do afastamento": Control("text", _DC_PROC + "text[17]"),
        "Fim do afastamento": Control("text", _DC_PROC + "text[19]"),
        "Descrição do afastamento": Control("text", _DC_PROC + "scroll pane[21].viewport[0].text[0]"),
        "Tabela de Investigados": Control("table", _DC_INV + "scroll pane[0].viewport[0].table[0]"),
        "Adicionar Investigado": Control("push button", _DC_INV + "push button[1]", "Adicionar"),
        "Remover Todos": Control("push button", _DC_INV + "push button[4]", "Remover Todos"),
        "Gravar": Control("push button", _DC + "push button[5]", "Gravar"),
        "Cancelar": Control("push button", _DC + "push button[6]", "Cancelar"),
    },
)

_IN = "root pane[0].layered pane[1].panel[0]."
INVESTIGADO = Screen(
    "Investigado",
    "Investigado",
    {
        "Pessoa Física": Control("radio button", _IN + "radio button[0]", "Pessoa Física"),
        "Pessoa Jurídica": Control("radio button", _IN + "radio button[1]", "Pessoa Jurídica"),
        "CPF": Control("text", _IN + "text[3]"),
        "CNPJ": Control("text", _IN + "text[4]"),
        "Nome": Control("text", _IN + "text[7]"),
        "Relacionamento Não": Control("radio button", _IN + "radio button[9]", "Não"),
        "Relacionamento Sim": Control("radio button", _IN + "radio button[10]", "Sim"),
        "Conta Depósito": Control("check box", _IN + "panel[11].check box[0]", "Conta Depósito"),
        "B/D/V - Bens, Direitos ou Valores": Control(
            "check box", _IN + "panel[11].check box[1]", "B/D/V - Bens, Direitos ou Valores"
        ),
        "Outras informações": Control("text", _IN + "scroll pane[13].viewport[0].text[0]"),
        "Salvar": Control("push button", _IN + "push button[19]", "Salvar"),
        "Cancelar": Control("push button", _IN + "push button[20]", "Cancelar"),
    },
)

# Diálogos de validação do Simba (JOptionPane): "Aviso" (ex.: "O dígito verificador está inválido.")
# e "Erro" (ex.: "O Número do Processo não poder ter mais de 20 caracteres.").
_OK = Control("push button", "root pane[0].layered pane[1].panel[0].alert[0].panel[1].push button[0]", "OK")
AVISO = Screen("Aviso", "Aviso", {"OK": _OK})
ERRO = Screen("Erro", "Erro", {"OK": _OK})
DIALOGOS_DE_VALIDACAO = [AVISO, ERRO]

_OPCOES = "root pane[0].layered pane[1].panel[0].option pane[0].panel[1]."
ATENCAO = Screen(
    "Atenção",
    "Atencão",  # sic: título da janela no Simba
    {
        "Sim": Control("push button", _OPCOES + "push button[0]", "Sim"),
        "Não": Control("push button", _OPCOES + "push button[1]", "Não"),
    },
)
INFORMACAO = Screen("Informação", "Informação", {"OK": _OK})

_P2 = "root pane[0].layered pane[1].panel[0].panel[0]."
PASSO_2 = Screen(
    "Passo 2",
    "",
    {
        "Atendimento": Control("label", _P2 + "label[1]"),
        "Pasta selecionada": Control("text", _P2 + "text[3]"),
        "Selecionar Pasta": Control("push button", _P2 + "push button[4]", "Selecionar Pasta"),
        "Mensagens": Control("text", _P2 + "scroll pane[9].viewport[0].text[0]"),
        "Voltar": Control("push button", _P2 + "push button[10]", "<< Voltar"),
        "Ver relatório": Control("push button", _P2 + "push button[11]", "Ver relatório"),
        "Continuar": Control("push button", _P2 + "push button[12]", "Continuar >>"),
        "Progresso": Control("label", _P2 + "label[18]"),
    },
    marker=Control("label", _P2 + "label[0]", "Passo 2 - Seleção de diretório de arquivos "),
)

_DIR = "root pane[0].layered pane[1].panel[0].file chooser[0].panel[2].panel[2]."
DIRETORIO = Screen(
    "Diretório",
    "Selecione diretório para validação",
    {
        "Pasta": Control("text", _DIR + "panel[2].text[1]", "Nome da pasta:"),
        "Selecionar Pasta": Control("push button", _DIR + "panel[4].push button[1]", "Selecionar Pasta"),
    },
)

_P3 = "root pane[0].layered pane[1].panel[0]."
PASSO_3 = Screen(
    "Passo 3",
    "",
    {
        "Atendimento": Control("label", _P3 + "label[1]"),
        "Gerar": Control("push button", _P3 + "push button[4]", "Gerar"),
        "Pasta dadosValidador": Control("label", _P3 + "label[10]"),
        "Hash": Control("label", _P3 + "label[12]"),
        "Mensagens": Control("text", _P3 + "scroll pane[14].viewport[0].text[0]"),
        "Voltar": Control("push button", _P3 + "push button[15]", "<< Voltar"),
        "Fechar": Control("push button", _P3 + "push button[16]", "Fechar"),
    },
    marker=Control("label", _P3 + "label[0]", "Passo 3 - Gerar arquivo para envio"),
)

ALL = [PASSO_1, DADOS_DO_CASO, INVESTIGADO, ATENCAO, INFORMACAO, PASSO_2, DIRETORIO, PASSO_3, *DIALOGOS_DE_VALIDACAO]
