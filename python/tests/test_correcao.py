"""Correção automática dos GABs (sem Simba): cada defeito conhecido vira exatamente o arquivo válido."""
import json
from pathlib import Path

import pytest
from gab_ficticio import DEFEITOS_CORRIGIVEIS, ENDERECO_ACENTUADO, crlf, gravar_gab, linhas_gab112

from simba import cadastro, correcao

DADOS = Path(__file__).parent / "data" / "caso_teste.json"
ERRO_LINHA_1 = (
    "Erro no arquivo: 002-PF-013110-03_GAB112.txt, linha: 1, erro: Certifique-se de completar com espaços os "
    "campos que não atingirem o tamanho predeterminado e Não use tab para separar os campos."
)


@pytest.fixture
def caso() -> cadastro.Caso:
    return cadastro.Caso.from_json(json.loads(DADOS.read_text(encoding="utf-8")))


@pytest.fixture
def linhas(caso: cadastro.Caso) -> list[str]:
    return linhas_gab112(caso, endereco=ENDERECO_ACENTUADO)


@pytest.mark.parametrize("defeito", DEFEITOS_CORRIGIVEIS)
def test_defeito_conhecido_vira_o_arquivo_valido(linhas: list[str], defeito: str) -> None:
    valido = crlf(linhas).encode("cp1252")

    corrigido, correcoes = correcao.corrigir_conteudo("X_GAB112.txt", DEFEITOS_CORRIGIVEIS[defeito](linhas))

    assert corrigido == valido
    assert correcoes and all(c.startswith("X_GAB112.txt: ") for c in correcoes)


def test_conversao_de_utf8_mantem_os_acentos(linhas: list[str]) -> None:
    corrigido, correcoes = correcao.corrigir_conteudo("X_GAB112.txt", crlf(linhas).encode("utf-8"))

    assert "PRAÇA 1ª TRAV 2º" in corrigido.decode("cp1252")
    assert correcoes == ["X_GAB112.txt: convertido de UTF-8 para Windows-1252 (caracteres: ª º Ç)"]


def test_caractere_sem_equivalente_vira_um_espaco_e_mantem_o_tamanho(caso: cadastro.Caso) -> None:
    linhas = linhas_gab112(caso, endereco="RUA ✓ 10")

    corrigido, correcoes = correcao.corrigir_conteudo("X_GAB112.txt", crlf(linhas).encode("utf-8"))

    assert [len(l) for l in corrigido.decode("cp1252").splitlines()] == [307] * len(linhas)
    assert "RUA   10" in corrigido.decode("cp1252")
    assert any("trocados por espaço: ✓" in c for c in correcoes)


def test_arquivo_valido_em_windows_1252_nao_e_alterado(linhas: list[str]) -> None:
    valido = crlf(linhas).encode("cp1252")

    assert correcao.corrigir_conteudo("X_GAB112.txt", valido) == (valido, [])


def test_linha_com_dados_alem_do_leiaute_nao_e_corrigida(linhas: list[str]) -> None:
    with pytest.raises(correcao.NaoCorrigivel, match="linha 1: 310 posições"):
        correcao.corrigir_conteudo("X_GAB112.txt", crlf([linhas[0] + "XYZ"]).encode("cp1252"))


def test_leiaute_versao_2_do_gab109_e_reconhecido() -> None:
    linha = "2" * 333

    corrigido, _ = correcao.corrigir_conteudo("X_GAB109.txt", f"{linha}\r\n{linha[:300]}\r\n".encode("cp1252"))

    assert corrigido == f"{linha}\r\n{linha[:300]}{' ' * 33}\r\n".encode("cp1252")


def test_le_os_erros_do_validador() -> None:
    mensagens = f"Iniciando...\n{ERRO_LINHA_1}\nRelatório de inconsistências gerado.\nFim da verificação."

    [erro] = correcao.erros_do_validador(mensagens)

    assert (erro.arquivo, erro.linha) == ("002-PF-013110-03_GAB112.txt", 1)
    assert erro.erro.startswith(correcao.ERRO_TAMANHO)


def test_corrige_a_pasta_quando_todos_os_erros_sao_conhecidos(
    caso: cadastro.Caso, linhas: list[str], tmp_path: Path
) -> None:
    gravar_gab(caso, tmp_path, crlf(linhas).encode("utf-8"))

    correcoes = correcao.corrigir(tmp_path, ERRO_LINHA_1)

    assert correcoes
    assert (tmp_path / f"{caso.pasta}_GAB112.txt").read_bytes() == crlf(linhas).encode("cp1252")


ERRO_DE_DADOS = (
    "Erro no arquivo: GAB112, linha: 0, erro: O investigado com CPF/CNPJ 11222333000181 "
    "não foi encontrado no arquivo cadastral(gab112)."
)


def test_erro_de_dados_sem_defeito_mecanico_nao_mexe_em_nada(
    caso: cadastro.Caso, linhas: list[str], tmp_path: Path
) -> None:
    valido = crlf(linhas).encode("cp1252")
    gravar_gab(caso, tmp_path, valido)

    assert correcao.corrigir(tmp_path, ERRO_DE_DADOS) == []
    assert (tmp_path / f"{caso.pasta}_GAB112.txt").read_bytes() == valido


def test_defeito_mecanico_e_corrigido_mesmo_com_erro_de_dados_junto(
    caso: cadastro.Caso, linhas: list[str], tmp_path: Path
) -> None:
    gravar_gab(caso, tmp_path, crlf(linhas).encode("utf-8"))

    # Com a linha deslocada, o Validador pode reportar erros de campo em vez do erro de tamanho.
    correcoes = correcao.corrigir(tmp_path, f"{ERRO_LINHA_1}\n{ERRO_DE_DADOS}")

    assert correcoes
    assert (tmp_path / f"{caso.pasta}_GAB112.txt").read_bytes() == crlf(linhas).encode("cp1252")


def test_sem_erro_do_validador_nao_corrige(caso: cadastro.Caso, linhas: list[str], tmp_path: Path) -> None:
    defeituoso = crlf(linhas).encode("utf-8")
    gravar_gab(caso, tmp_path, defeituoso)

    assert correcao.corrigir(tmp_path, "Ocorreu um erro do sistema durante a validação.") == []
    assert (tmp_path / f"{caso.pasta}_GAB112.txt").read_bytes() == defeituoso
