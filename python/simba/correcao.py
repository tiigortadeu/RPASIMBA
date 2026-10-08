"""Correção automática de erros conhecidos nos arquivos GAB (posicionais) reprovados pelo Simba Validador.

O Validador lê os GABs na codificação padrão da JVM (Windows-1252) e corta os campos por posição. Testado no
Simba 5.8.7: quando uma linha não tem exatamente o tamanho do leiaute, ele reprova com "Certifique-se de completar
com espaços...". Causas encontradas, todas corrigidas aqui sem alterar o conteúdo dos campos:

- arquivo em UTF-8: cada acento (ª, º, ç, é...) ocupa 2 bytes e desloca a linha -> converte para Windows-1252,
  mantendo os caracteres (o que não existe em Windows-1252 vira espaço, 1 posição por caractere);
- BOM (EF BB BF) no início -> removido;
- linha em branco (inclusive no fim do arquivo) -> removida;
- linha mais curta que o leiaute (espaços finais cortados) -> completada com espaços;
- linha mais longa só por espaços finais -> espaços excedentes removidos.

Depois de corrigir, valida de novo: qualquer erro de dados (CPF inválido, data, investigado ausente) continua
reprovando, para o usuário tratar, com a lista das correções já aplicadas.
"""
import re
from dataclasses import dataclass
from pathlib import Path

ERRO_TAMANHO = "Certifique-se de completar com espaços os campos que não atingirem o tamanho predeterminado"
_ERRO = re.compile(r"Erro no arquivo: (?P<arquivo>.+?), linha: (?P<linha>\d+), erro: (?P<erro>.+)")

# Tamanho da linha de cada GAB por versão do leiaute (enums CamposGab*/CamposGab*Ver2 do simba-validador.jar 5.8.7).
# A versão 2 do GAB112 tem campos de tamanho não confirmado e fica de fora.
TAMANHOS = {
    "GAB109": (127, 333),
    "GAB112": (307,),
    "GAB800": (298, 320),
}
CODIFICACAO_SIMBA = "cp1252"
BOM = b"\xef\xbb\xbf"


class NaoCorrigivel(Exception):
    pass


@dataclass
class ErroValidador:
    arquivo: str
    linha: int
    erro: str


def erros_do_validador(mensagens: str) -> list[ErroValidador]:
    return [
        ErroValidador(m["arquivo"].strip(), int(m["linha"]), m["erro"].strip())
        for m in map(_ERRO.search, mensagens.splitlines())
        if m
    ]


def _tipo_gab(nome_arquivo: str) -> str:
    for tipo in TAMANHOS:
        if nome_arquivo.upper().endswith(f"_{tipo}.TXT"):
            return tipo
    raise NaoCorrigivel(f"{nome_arquivo}: não é um arquivo GAB com leiaute conhecido")


def _decodificar(conteudo: bytes) -> tuple[str, str, list[str]]:
    """Texto, codificação de saída e correções. Fora do caso UTF-8 os bytes são preservados (latin-1 ida e volta)."""
    correcoes = []
    if conteudo.startswith(BOM):
        conteudo = conteudo[len(BOM) :]
        correcoes.append("BOM removido do início do arquivo")
    if any(b >= 0x80 for b in conteudo):
        try:
            texto = conteudo.decode("utf-8")
        except UnicodeDecodeError:
            # Não é UTF-8: já está no single-byte que o Simba lê.
            return conteudo.decode("latin-1"), "latin-1", correcoes
        acentos = sorted({c for c in texto if ord(c) >= 0x80})
        correcoes.append(f"convertido de UTF-8 para Windows-1252 (caracteres: {' '.join(acentos)})")
        return texto, CODIFICACAO_SIMBA, correcoes
    return conteudo.decode("latin-1"), "latin-1", correcoes


def _codificar(texto: str, codificacao: str) -> tuple[bytes, list[str]]:
    saida, trocados = [], set()
    for c in texto:
        try:
            saida.append(c.encode(codificacao))
        except UnicodeEncodeError:
            # Mantém o tamanho da linha: um caractere vira uma posição.
            saida.append(b" ")
            trocados.add(c)
    if not trocados:
        return b"".join(saida), []
    return b"".join(saida), [f"caracteres sem equivalente em Windows-1252 trocados por espaço: {' '.join(sorted(trocados))}"]


def corrigir_conteudo(nome: str, original: bytes) -> tuple[bytes, list[str]]:
    """Conteúdo corrigido do GAB `nome` e a descrição de cada correção (vazia se nada mudou)."""
    tamanhos = TAMANHOS[_tipo_gab(nome)]
    texto, codificacao, correcoes = _decodificar(original)
    linhas = texto.splitlines()

    em_branco = [n for n, linha in enumerate(linhas, start=1) if not linha.strip()]
    linhas = [linha for linha in linhas if linha.strip()]
    if em_branco:
        correcoes.append(f"linhas em branco removidas: {', '.join(map(str, em_branco))}")

    # Versão do leiaute: a que bate com mais linhas (empate fica com a versão 1).
    tamanho = max(tamanhos, key=lambda t: sum(len(linha) == t for linha in linhas))
    completadas, aparadas = [], []
    for i, linha in enumerate(linhas):
        if len(linha) < tamanho:
            linhas[i] = linha.ljust(tamanho)
            completadas.append(i + 1)
        elif len(linha) > tamanho:
            if linha[tamanho:].strip():
                raise NaoCorrigivel(
                    f"{nome}, linha {i + 1}: {len(linha)} posições (esperado {tamanho}) com dados além do leiaute"
                )
            linhas[i] = linha[:tamanho]
            aparadas.append(i + 1)
    if completadas:
        correcoes.append(f"linhas completadas com espaços até {tamanho} posições: {_resumo(completadas)}")
    if aparadas:
        correcoes.append(f"espaços excedentes removidos (linhas com mais de {tamanho} posições): {_resumo(aparadas)}")

    conteudo, trocas = _codificar("".join(f"{linha}\r\n" for linha in linhas), codificacao)
    if conteudo == original:
        return original, []
    return conteudo, [f"{nome}: {c}" for c in correcoes + trocas]


def _resumo(linhas: list[int], limite: int = 10) -> str:
    texto = ", ".join(map(str, linhas[:limite]))
    return texto + (f" e mais {len(linhas) - limite}" if len(linhas) > limite else "")


def corrigir(pasta: Path, mensagens: str) -> list[str]:
    """Corrige defeitos mecânicos dos GABs da pasta depois de uma reprovação do Validador.

    Não depende do texto de cada erro: com acentos em UTF-8, o Validador às vezes reporta erros de campo
    (linha deslocada) em vez do erro de tamanho. As correções só mexem em codificação, BOM, linhas em branco
    e espaços de preenchimento; erros de dados continuam reprovando na nova validação.
    Devolve [] (sem alterar nada) se não houver o que corrigir ou se algum arquivo não puder ser corrigido.
    """
    if not erros_do_validador(mensagens):
        return []
    corrigidos: dict[Path, bytes] = {}
    correcoes: list[str] = []
    try:
        for arquivo in sorted(pasta.iterdir()):
            if not any(arquivo.name.upper().endswith(f"_{tipo}.TXT") for tipo in TAMANHOS):
                continue
            conteudo, descricoes = corrigir_conteudo(arquivo.name, arquivo.read_bytes())
            if descricoes:
                corrigidos[arquivo] = conteudo
                correcoes += descricoes
    except NaoCorrigivel:
        return []
    # Só grava se todos os arquivos tiverem correção: nada fica pela metade.
    for arquivo, conteudo in corrigidos.items():
        arquivo.write_bytes(conteudo)
    return correcoes
