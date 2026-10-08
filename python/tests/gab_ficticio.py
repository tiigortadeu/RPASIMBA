"""Gera arquivos GAB fictícios para testar a validação do Simba (botão "Validar Arquivos GAB").

Leiaute do GAB112 (dados cadastrais, posicional, 307 posições) conforme o enum CamposGab112 do
simba-validador.jar 5.8.7: numéricos com zeros à esquerda, texto com espaços à direita, datas AAAAMMDD,
tipo de pessoa F/J, constante 0000A, mercado BOVESPA/BMF/SWAP. GAB109 e GAB800 podem ir vazios.
"""
from pathlib import Path

from simba.cadastro import Caso

# (campo, tamanho, numérico)
CAMPOS_GAB112 = [
    ("codigo_cliente", 7, True),
    ("documento", 15, True),
    ("data_criacao", 8, True),
    ("data_atualizacao", 8, True),
    ("data_nascimento_fundacao", 8, True),
    ("tipo_pessoa", 1, False),
    ("nome", 60, False),
    ("documento_identificacao", 10, False),
    ("nome_conjuge", 60, False),
    ("codigo_cliente_mercado", 7, True),
    ("endereco", 30, False),
    ("numero_complemento", 15, False),
    ("bairro", 18, False),
    ("cidade", 18, False),
    ("uf", 2, False),
    ("cep", 5, True),
    ("complemento_cep", 3, True),
    ("constante", 5, False),
    ("codigo_atividade", 3, True),
    ("telefone", 14, True),
    ("mercado", 10, False),
]
TAMANHO_LINHA_GAB112 = sum(tamanho for _, tamanho, _ in CAMPOS_GAB112)

_PADRAO = {
    "data_criacao": "20200115",
    "data_atualizacao": "20250110",
    "documento_identificacao": "123456789",
    "codigo_cliente_mercado": "1",
    "endereco": "RUA TESTE",
    "numero_complemento": "100",
    "bairro": "CENTRO",
    "cidade": "SAO PAULO",
    "uf": "SP",
    "cep": "01310",
    "complemento_cep": "100",
    "constante": "0000A",
    "codigo_atividade": "1",
    "telefone": "11999999999",
    "mercado": "BOVESPA",
}


def linha_gab112(**valores: str) -> str:
    dados = {**_PADRAO, **valores}
    linha = ""
    for campo, tamanho, numerico in CAMPOS_GAB112:
        valor = str(dados.get(campo, ""))
        if len(valor) > tamanho:
            raise ValueError(f"{campo}={valor!r} excede {tamanho} posições")
        linha += valor.rjust(tamanho, "0") if numerico else valor.ljust(tamanho)
    return linha


def linhas_gab112(caso: Caso, **valores: str) -> list[str]:
    """Uma linha válida por investigado do caso; `valores` sobrescreve campos de todas (ex.: endereco=...)."""
    return [
        linha_gab112(
            **{
                "codigo_cliente": str(i),
                "documento": inv.documento,
                "tipo_pessoa": "F" if inv.tipo == "PF" else "J",
                "data_nascimento_fundacao": "19800101" if inv.tipo == "PF" else "20100101",
                "nome": inv.nome.upper(),
                **valores,
            }
        )
        for i, inv in enumerate(caso.investigados, start=1)
    ]


def crlf(linhas) -> str:
    return "".join(f"{l}\r\n" for l in linhas)


# Defeitos reais que o Simba 5.8.7 reprova com "Certifique-se de completar com espaços..." (testados um a um).
# Cada função recebe as linhas válidas e devolve os bytes do GAB112 defeituoso.
DEFEITOS_CORRIGIVEIS = {
    "utf8_com_acentos": lambda linhas: crlf(linhas).encode("utf-8"),
    "bom_utf8": lambda linhas: b"\xef\xbb\xbf" + crlf(linhas).encode("cp1252"),
    "linha_sem_espacos_finais": lambda linhas: crlf(l.rstrip() for l in linhas).encode("cp1252"),
    "linha_com_espacos_a_mais": lambda linhas: crlf(l + "   " for l in linhas).encode("cp1252"),
    "linha_em_branco_no_fim": lambda linhas: (crlf(linhas) + "\r\n").encode("cp1252"),
    "utf8_bom_e_linha_curta": lambda linhas: b"\xef\xbb\xbf" + crlf(l.rstrip() for l in linhas).encode("utf-8"),
}
# Endereço com "ª", "º" e "Ç" (o Simba aceita em Windows-1252; em UTF-8, desloca a linha).
ENDERECO_ACENTUADO = "PRAÇA 1ª TRAV 2º"


def gravar_gab(caso: Caso, pasta: Path, gab112: bytes) -> Path:
    """Grava o GAB112 com o conteúdo exato (para testar arquivos defeituosos); GAB109 e GAB800 vazios."""
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{caso.pasta}_GAB109.txt").write_bytes(b"")
    (pasta / f"{caso.pasta}_GAB800.txt").write_bytes(b"")
    (pasta / f"{caso.pasta}_GAB112.txt").write_bytes(gab112)
    return pasta


def gerar_gab(caso: Caso, pasta: Path) -> Path:
    """GAB112 com um cliente por investigado do caso; GAB109 e GAB800 vazios."""
    return gravar_gab(caso, pasta, "".join(f"{l}\r\n" for l in linhas_gab112(caso)).encode("latin-1"))
