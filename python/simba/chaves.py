"""Chaves do Transmissor: arquivo .ASB e senha de cada órgão, lidos do CSV de chaves (SIMBA_CHAVES_CSV).

O CSV tem as colunas NOME DA CHAVE; SENHA; RESPONSÁVEL (separador ";", exportado do Excel). O órgão é o código
de três dígitos no nome da chave (ex.: "002-PF RESPONSAVEL.ASB" e "CHAVE 002.ASB" são do órgão 002). Com mais de uma
linha para o mesmo órgão, vale a chave cujo arquivo existe em SIMBA_CHAVES_DIR.

As senhas nunca são registradas em log nem enviadas ao console: só se estão preenchidas.
"""
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from simba import config

_ORGAO = re.compile(r"(?<!\d)(\d{3})(?!\d)")
COLUNA_NOME = "NOME DA CHAVE"
COLUNA_SENHA = "SENHA"
COLUNA_RESPONSAVEL = "RESPONSÁVEL"


class ChaveIndisponivel(Exception):
    """Chave do órgão ausente ou incompleta (CSV, arquivo ou senha). Exige ação manual na configuração."""


@dataclass
class Chave:
    orgao: str
    arquivo: str
    senha: str
    responsavel: str

    @property
    def caminho(self) -> Path:
        return config.CHAVES_DIR / self.arquivo

    @property
    def existe(self) -> bool:
        return self.caminho.is_file()


def orgao_do_atendimento(atendimento: str) -> str:
    """002-PF-013110-03 -> 002."""
    return atendimento.split("-", 1)[0]


def ler(arquivo_csv: Optional[Path] = None) -> list[Chave]:
    """Todas as linhas válidas do CSV (com nome de chave e código de órgão), na ordem do arquivo."""
    arquivo_csv = arquivo_csv or config.CHAVES_CSV
    if not arquivo_csv.is_file():
        raise ChaveIndisponivel(f"CSV de chaves não encontrado: {arquivo_csv} (SIMBA_CHAVES_CSV no .env)")
    bruto = arquivo_csv.read_bytes()
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = bruto.decode("cp1252")
    linhas = list(csv.reader(texto.splitlines(), delimiter=";"))
    if not linhas:
        return []
    cabecalho = [c.strip().upper() for c in linhas[0]]
    try:
        i_nome, i_senha = cabecalho.index(COLUNA_NOME), cabecalho.index(COLUNA_SENHA)
    except ValueError:
        raise ChaveIndisponivel(f"O CSV de chaves precisa das colunas {COLUNA_NOME} e {COLUNA_SENHA}: {arquivo_csv}")
    i_resp = cabecalho.index(COLUNA_RESPONSAVEL) if COLUNA_RESPONSAVEL in cabecalho else None

    def celula(linha: list[str], i: Optional[int]) -> str:
        return linha[i].strip() if i is not None and i < len(linha) else ""

    chaves = []
    for linha in linhas[1:]:
        nome = celula(linha, i_nome)
        orgao = _ORGAO.search(nome)
        if nome and orgao:
            chaves.append(Chave(orgao.group(1), nome, celula(linha, i_senha), celula(linha, i_resp)))
    return chaves


def por_orgao(chaves: list[Chave]) -> dict[str, list[Chave]]:
    agrupadas: dict[str, list[Chave]] = {}
    for chave in chaves:
        agrupadas.setdefault(chave.orgao, []).append(chave)
    return agrupadas


def escolher(candidatas: list[Chave]) -> Chave:
    """A chave do órgão: a primeira cujo arquivo existe na pasta (ou a primeira do CSV, para o erro ser claro)."""
    return next((c for c in candidatas if c.existe), candidatas[0])


def da_orgao(orgao: str) -> tuple[Path, str]:
    """(arquivo .ASB, senha) do órgão; ChaveIndisponivel com a explicação se faltar algo."""
    candidatas = por_orgao(ler()).get(orgao)
    if not candidatas:
        raise ChaveIndisponivel(f"Órgão {orgao} sem chave no CSV de chaves ({config.CHAVES_CSV.name})")
    chave = escolher(candidatas)
    if not chave.existe:
        raise ChaveIndisponivel(f"Arquivo de chaves do órgão {orgao} não encontrado: {chave.caminho}")
    if not chave.senha:
        raise ChaveIndisponivel(f"Senha da chave {chave.arquivo} (órgão {orgao}) está vazia no CSV de chaves")
    return chave.caminho, chave.senha


def situacao(chave: Chave) -> str:
    if not chave.existe:
        return "Arquivo .ASB não encontrado na pasta"
    if not chave.senha:
        return "Senha vazia no CSV"
    return "OK"
