"""Cadastro de atendimento com o caso fictício tests/data/caso_teste.json (002-PF-013110-03).

Grava no Simba local (dadosValidador). Rodar com: pytest -m cadastro
"""
import json
from pathlib import Path

import pytest

from simba import cadastro, config, screens
from simba.app import SimbaApp, SimbaAviso

pytestmark = pytest.mark.cadastro

DADOS = Path(__file__).parent / "data" / "caso_teste.json"


@pytest.fixture
def caso() -> cadastro.Caso:
    return cadastro.Caso.from_json(json.loads(DADOS.read_text(encoding="utf-8")))


def test_dv_invalido_falha_com_mensagem_do_simba_sem_retentar(simba: SimbaApp, caso: cadastro.Caso) -> None:
    caso.dv = "99"

    with pytest.raises(SimbaAviso, match="dígito verificador está inválido"):
        simba.run_step("cadastro_dv_invalido", lambda app: cadastro.abrir_caso(app, caso))

    assert simba.timings[-1].attempts == 1
    assert not simba.is_open(screens.AVISO)


def test_preenche_dados_do_caso_e_investigados(simba: SimbaApp, caso: cadastro.Caso) -> None:
    simba.run_step("cadastro_preencher", lambda app: cadastro.preencher_caso(app, caso))

    lido = cadastro.ler_dados_do_caso(simba)
    esperado = {atributo: getattr(caso, atributo) for atributo in cadastro.CAMPOS_DADOS_DO_CASO.values()}
    # O Simba aplica a máscara no CNPJ.
    assert lido.pop("cnpj").replace(".", "").replace("/", "").replace("-", "") == esperado.pop("cnpj")
    assert lido == esperado

    investigados = cadastro.ler_investigados(simba)
    assert [(i["Tipo"], i["CPF_CNPJ"], i["Nome"]) for i in investigados] == [
        (inv.tipo, inv.documento, inv.nome.upper()) for inv in caso.investigados
    ]
    assert all(i["Relac"] == i["Conta"] == i["B/D/V"] == "Sim" for i in investigados)


def test_processo_com_mais_de_20_caracteres_falha_ao_gravar(simba: SimbaApp, caso: cadastro.Caso) -> None:
    caso.processo = "0000000-00.2026.8.26.0001"

    def etapa(app: SimbaApp) -> str:
        cadastro.preencher_caso(app, caso)
        return cadastro.gravar(app)

    with pytest.raises(SimbaAviso, match="20 caracteres"):
        simba.run_step("cadastro_processo_longo", etapa)


def test_grava_caso_e_atendimento_aparece_no_passo1(simba: SimbaApp, caso: cadastro.Caso) -> None:
    def etapa(app: SimbaApp) -> str:
        cadastro.preencher_caso(app, caso)
        return cadastro.gravar(app)

    mensagem = simba.run_step("cadastro_gravar", etapa)

    assert mensagem == "Dados do caso gravados com sucesso."
    lista = simba.control(screens.PASSO_1, "Atendimento a Validar")
    atendimentos = [e.name for _, e in lista.walk() if e is not lista]
    assert atendimentos.count(caso.pasta) == 1
    assert (config.SIMBA_VALIDADOR_DADOS / caso.pasta).is_dir()
