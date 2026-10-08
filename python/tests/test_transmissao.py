"""Simba Transmissor com o atendimento fictício 002-PF-013110-03, até a senha da chave.

Nunca aciona o Enviar: não há arquivo de chaves real nesta máquina e o envio vai para o órgão (produção).
Os testes marcados com `cadastro` geram o atendimento se preciso. Rodar com: pytest -m cadastro
"""
import json
import zipfile
from pathlib import Path

import pytest
from gab_ficticio import gerar_gab

from simba import arquivo, cadastro, fluxo, screens, transmissao
from simba.app import SimbaApp, SimbaAviso

DADOS = Path(__file__).parent / "data" / "caso_teste.json"


@pytest.fixture
def caso() -> cadastro.Caso:
    return cadastro.Caso.from_json(json.loads(DADOS.read_text(encoding="utf-8")))


@pytest.fixture
def atendimento(
    simba: SimbaApp, transmissor: SimbaApp, caso: cadastro.Caso, tmp_path_factory: pytest.TempPathFactory
) -> str:
    """Garante o pacote de envio do atendimento de teste gerado pelo Validador."""
    pacote = arquivo.dados_transmissor(caso.pasta) / "envio" / f"{caso.pasta}.zip"
    if not pacote.is_file():
        fluxo.processar(simba, caso, gerar_gab(caso, tmp_path_factory.mktemp("gab")))
        arquivo.sincronizar_transmissor(caso.pasta)
        # O Transmissor só lê a lista de atendimentos ao abrir.
        transmissor.kill()
    return caso.pasta


@pytest.fixture
def chave_falsa(tmp_path: Path) -> Path:
    chave = tmp_path / "chave_falsa.txt"
    chave.write_text("não é um arquivo de chaves", encoding="utf-8")
    return chave


def _carregar(transmissor: SimbaApp, atendimento: str, chave: Path, senha: str) -> None:
    def etapa(app: SimbaApp) -> None:
        transmissao.selecionar_atendimento(app, atendimento)
        transmissao.carregar_chave(app, chave, senha)

    transmissor.run_step("transmissor_chave", etapa)


@pytest.mark.cadastro
def test_seleciona_atendimento_validado_e_ainda_nao_enviado(transmissor: SimbaApp, atendimento: str) -> None:
    situacao = transmissor.run_step(
        "transmissor_atendimento", lambda app: transmissao.selecionar_atendimento(app, atendimento)
    )

    assert situacao.startswith(atendimento)
    assert "ainda não foram enviados" in situacao


@pytest.mark.cadastro
def test_atendimento_fora_da_lista_falha_sem_retentar(transmissor: SimbaApp, atendimento: str) -> None:
    with pytest.raises(SimbaAviso, match="não está disponível no Transmissor"):
        transmissor.run_step(
            "transmissor_inexistente", lambda app: transmissao.selecionar_atendimento(app, "002-PF-999999-99")
        )

    assert transmissor.timings[-1].attempts == 1


@pytest.mark.cadastro
def test_chave_inexistente_falha_com_mensagem_do_transmissor(
    transmissor: SimbaApp, atendimento: str, tmp_path: Path
) -> None:
    with pytest.raises(SimbaAviso, match="Arquivo não localizado"):
        _carregar(transmissor, atendimento, tmp_path / "nao_existe.chave", "12345678")

    assert not transmissor.is_open(screens.INFORMACAO)


@pytest.mark.cadastro
def test_senha_fora_do_tamanho_falha_com_mensagem_do_transmissor(
    transmissor: SimbaApp, atendimento: str, chave_falsa: Path
) -> None:
    with pytest.raises(SimbaAviso, match="entre 8 e 16 caracteres"):
        _carregar(transmissor, atendimento, chave_falsa, "123")


@pytest.mark.cadastro
def test_chave_invalida_nao_habilita_enviar(transmissor: SimbaApp, atendimento: str, chave_falsa: Path) -> None:
    with pytest.raises(SimbaAviso, match="Arquivo de chaves inválido ou senha incorreta"):
        _carregar(transmissor, atendimento, chave_falsa, "senha-de-teste")

    enviar = transmissor.control(screens.TRANSMISSOR, "Enviar")
    assert "enabled" not in enviar.refresh().states.split(",")


def test_arquiva_todos_os_arquivos_validados_num_zip(tmp_path: Path) -> None:
    origem = tmp_path / "gab"
    origem.mkdir()
    nomes = ["X_GAB109.txt", "X_GAB112.txt", "X_GAB800.txt"]
    for nome in nomes:
        (origem / nome).write_text(nome, encoding="utf-8")

    pacote = transmissao.arquivar_arquivos("002-PF-013110-03", origem, tmp_path / "Transmitidos" / "002-PF-013110-03")

    # Uma pasta por caso: o zip fica ao lado do comprovante PDF, sem subpastas.
    assert pacote == tmp_path / "Transmitidos" / "002-PF-013110-03" / "002-PF-013110-03_GABs.zip"
    with zipfile.ZipFile(pacote) as z:
        assert sorted(z.namelist()) == nomes
        assert z.read("X_GAB112.txt").decode() == "X_GAB112.txt"
