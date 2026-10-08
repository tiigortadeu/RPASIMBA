"""dadosValidador separado por programa (Validador\\5.8.7 e Transmissor\\4.6.7) ou compartilhado (exe em <SIMBA_HOME>)."""
from pathlib import Path

import pytest

from simba import arquivo, config

ATENDIMENTO = "002-PF-013110-03"


@pytest.fixture
def separados(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "SIMBA_VALIDADOR_DADOS", tmp_path / "Validador" / "dadosValidador")
    monkeypatch.setattr(config, "SIMBA_TRANSMISSOR_DADOS", tmp_path / "Transmissor" / "dadosValidador")
    monkeypatch.setattr(config, "ARQUIVO_DIR", tmp_path / "Arquivo")
    envio = arquivo.dados_validador(ATENDIMENTO) / "envio"
    envio.mkdir(parents=True)
    (envio / f"{ATENDIMENTO}.zip").write_bytes(b"pacote novo")
    return tmp_path


def test_copia_o_atendimento_para_o_transmissor_substituindo_copia_anterior(separados: Path) -> None:
    antigo = arquivo.dados_transmissor(ATENDIMENTO) / "envio"
    antigo.mkdir(parents=True)
    (antigo / "obsoleto.txt").write_text("x")

    arquivo.sincronizar_transmissor(ATENDIMENTO)

    envio = arquivo.dados_transmissor(ATENDIMENTO) / "envio"
    assert (envio / f"{ATENDIMENTO}.zip").read_bytes() == b"pacote novo"
    assert not (envio / "obsoleto.txt").exists()


def test_sem_dados_do_validador_falha(separados: Path) -> None:
    with pytest.raises(FileNotFoundError):
        arquivo.sincronizar_transmissor("002-PF-999999-99")


def test_arquiva_as_duas_copias(separados: Path) -> None:
    arquivo.sincronizar_transmissor(ATENDIMENTO)

    destino = arquivo.arquivar_atendimento(ATENDIMENTO)

    assert destino == separados / "Arquivo" / ATENDIMENTO
    assert (separados / "Arquivo" / "Transmissor" / ATENDIMENTO / "envio" / f"{ATENDIMENTO}.zip").is_file()
    assert not arquivo.dados_validador(ATENDIMENTO).exists()
    assert not arquivo.dados_transmissor(ATENDIMENTO).exists()


def test_pasta_compartilhada_nao_copia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dados = tmp_path / "dadosValidador"
    monkeypatch.setattr(config, "SIMBA_VALIDADOR_DADOS", dados)
    monkeypatch.setattr(config, "SIMBA_TRANSMISSOR_DADOS", dados)
    (dados / ATENDIMENTO).mkdir(parents=True)

    arquivo.sincronizar_transmissor(ATENDIMENTO)

    assert [p.name for p in dados.iterdir()] == [ATENDIMENTO]
