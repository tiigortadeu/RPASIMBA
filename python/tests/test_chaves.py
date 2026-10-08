"""Chave do Transmissor de cada órgão, lida do CSV de chaves (NOME DA CHAVE;SENHA;RESPONSÁVEL)."""
from pathlib import Path

import pytest

from simba import chaves, config

CSV = (
    "NOME DA CHAVE;SENHA;RESPONSÁVEL;;\r\n"
    "001-MPF RESP-A.ASB;11111111;Responsável A;;\r\n"
    "002-PF RESP-A.ASB;22222222;Responsável A;;\r\n"
    "CHAVE 002.ASB;senha-002;Responsável A;;\r\n"
    "046-PCDF.RESP-B.ASB;;Responsável B;;\r\n"
    ";;;;\r\n"
)


@pytest.fixture
def pasta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "chaves.csv").write_bytes(CSV.encode("cp1252"))
    (tmp_path / "CHAVE 002.ASB").write_bytes(b"chave")
    (tmp_path / "046-PCDF.RESP-B.ASB").write_bytes(b"chave")
    monkeypatch.setattr(config, "CHAVES_DIR", tmp_path)
    monkeypatch.setattr(config, "CHAVES_CSV", tmp_path / "chaves.csv")
    return tmp_path


def test_le_o_csv_exportado_do_excel(pasta: Path) -> None:
    grupos = chaves.por_orgao(chaves.ler())

    assert sorted(grupos) == ["001", "002", "046"]
    assert [c.arquivo for c in grupos["002"]] == ["002-PF RESP-A.ASB", "CHAVE 002.ASB"]
    assert grupos["046"][0].responsavel == "Responsável B"


def test_com_duas_chaves_no_orgao_vale_a_que_existe_na_pasta(pasta: Path) -> None:
    assert chaves.da_orgao("002") == (pasta / "CHAVE 002.ASB", "senha-002")


def test_explica_o_que_falta_em_cada_orgao(pasta: Path) -> None:
    with pytest.raises(chaves.ChaveIndisponivel, match="não encontrado"):
        chaves.da_orgao("001")
    with pytest.raises(chaves.ChaveIndisponivel, match="Senha .* vazia"):
        chaves.da_orgao("046")
    with pytest.raises(chaves.ChaveIndisponivel, match="sem chave no CSV"):
        chaves.da_orgao("999")


def test_orgao_vem_do_atendimento() -> None:
    assert chaves.orgao_do_atendimento("002-PF-013110-03") == "002"
