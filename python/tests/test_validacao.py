"""Passo 2 com o atendimento fictício 002-PF-013110-03 (cadastrado pelo test_cadastro). Rodar com: pytest -m cadastro"""
import json
from pathlib import Path

import pytest
from gab_ficticio import gerar_gab

from simba import cadastro, screens, validacao
from simba.app import SimbaApp

pytestmark = pytest.mark.cadastro

DADOS = Path(__file__).parent / "data" / "caso_teste.json"


@pytest.fixture
def caso() -> cadastro.Caso:
    return cadastro.Caso.from_json(json.loads(DADOS.read_text(encoding="utf-8")))


@pytest.fixture
def atendimento(simba: SimbaApp, caso: cadastro.Caso) -> str:
    """Garante o atendimento de teste gravado no Simba e devolve o nome dele."""

    def garantir(app: SimbaApp) -> None:
        lista = app.control(screens.PASSO_1, "Atendimento a Validar")
        if caso.pasta not in [e.name for _, e in lista.walk() if e is not lista]:
            cadastro.preencher_caso(app, caso)
            cadastro.gravar(app)

    simba.run_step("garantir_atendimento", garantir)
    return caso.pasta


@pytest.mark.parametrize(
    "tipo, arquivo_esperado",
    [("Corretora", "_GAB109.txt"), ("Banco", "_AGENCIAS.txt")],
)
def test_pasta_sem_arquivos_e_reprovada_e_volta_ao_passo1(
    simba: SimbaApp, atendimento: str, tmp_path: Path, tipo: str, arquivo_esperado: str
) -> None:
    with pytest.raises(validacao.ArquivosReprovados) as reprovado:
        simba.run_step(f"validar_{tipo}", lambda app: validacao.validar_arquivos(app, atendimento, tipo, tmp_path))

    assert f"Arquivo esperado ({atendimento}{arquivo_esperado}) não encontrado." in reprovado.value.message
    assert simba.timings[-1].attempts == 1
    assert simba.is_open(screens.PASSO_1)


def test_atendimento_inexistente_falha_sem_retentar(simba: SimbaApp, tmp_path: Path) -> None:
    with pytest.raises(validacao.SimbaAviso, match="não está cadastrado"):
        simba.run_step("validar_inexistente", lambda app: validacao.validar_arquivos(app, "002-PF-999999-99", "Corretora", tmp_path))

    assert simba.timings[-1].attempts == 1


def test_gab_ficticio_valido_e_aprovado(simba: SimbaApp, atendimento: str, caso: cadastro.Caso, tmp_path: Path) -> None:
    pasta = gerar_gab(caso, tmp_path)

    resultado = simba.run_step("validar_gab_ok", lambda app: validacao.validar_arquivos(app, atendimento, "Corretora", pasta))

    assert resultado.aprovado
    for arquivo in ("GAB109", "GAB112", "GAB800"):
        assert f"Arquivo {arquivo}: conteúdo validado com êxito." in resultado.mensagens
    assert "enabled" in simba.control(screens.PASSO_2, "Continuar").refresh().states.split(",")


def test_gab112_sem_um_investigado_e_reprovado(
    simba: SimbaApp, atendimento: str, caso: cadastro.Caso, tmp_path: Path
) -> None:
    faltando = caso.investigados.pop()
    pasta = gerar_gab(caso, tmp_path)

    with pytest.raises(validacao.ArquivosReprovados, match=f"{faltando.documento} não foi encontrado no arquivo cadastral"):
        simba.run_step("validar_gab_incompleto", lambda app: validacao.validar_arquivos(app, atendimento, "Corretora", pasta))

    assert simba.is_open(screens.PASSO_1)
