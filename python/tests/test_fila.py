"""Protocolo de reserva das filas contra o ServiceNow do .env (DEV), numa fila de teste dedicada.

Cria e exclui os próprios work items. Rodar com: pytest -m servicenow
A fila de teste (SN_FILA_TESTE, padrão "Simba Runner Teste") não pode ter robôs do RPA Hub consumindo.
"""
import os
import uuid
from pathlib import Path

import pytest

from simba import config
from simba.fila import TABELA, Fila, ReservaPerdida
from simba.servicenow import ServiceNow

pytestmark = pytest.mark.servicenow

FILA_TESTE = os.environ.get("SN_FILA_TESTE", "Simba Runner Teste")


def _sn() -> ServiceNow:
    if not (config.SN_INSTANCIA and config.SN_USUARIO and config.SN_SENHA):
        pytest.skip("SN_INSTANCIA, SN_USUARIO e SN_SENHA não configurados no .env")
    return ServiceNow(config.SN_INSTANCIA, config.SN_USUARIO, config.SN_SENHA)


@pytest.fixture(scope="module")
def sn() -> ServiceNow:
    return _sn()


@pytest.fixture(scope="module")
def fila_id(sn: ServiceNow) -> str:
    filas = sn.listar("sn_rpa_fdn_work_queue", f"name={FILA_TESTE}", "sys_id", 1)
    if not filas:
        pytest.skip(f"Fila de teste {FILA_TESTE!r} não existe no ServiceNow")
    return filas[0]["sys_id"]


@pytest.fixture
def criar_itens(sn: ServiceNow, fila_id: str):
    criados: list[str] = []
    lote = uuid.uuid4().hex[:8]

    def criar(quantidade: int) -> list[str]:
        for i in range(quantidade):
            item = sn.criar(
                TABELA,
                {
                    "work_queue": fila_id,
                    "name": f"TesteRunner_{lote}_{i:02d}",
                    "status": "pending",
                    "request_content": '{"teste": true}',
                },
            )
            criados.append(item["sys_id"])
        return list(criados)

    yield criar
    for sys_id in criados:
        sn.excluir(TABELA, sys_id)


def _consumir(runner_id: str) -> list[str]:
    """Um runner: reserva até a fila esvaziar e conclui cada item na hora."""
    fila = Fila(_sn(), FILA_TESTE, runner_id=runner_id)
    reservados = []
    while (item := fila.reservar()) is not None:
        reservados.append(item.sys_id)
        fila.concluir(item, f"concluído por {runner_id}")
    return reservados


def test_runner_consome_todos_os_itens_com_uma_listagem(sn: ServiceNow, criar_itens) -> None:
    itens = criar_itens(5)

    reservados = _consumir("teste")

    assert sorted(reservados) == sorted(itens)
    for sys_id in itens:
        assert sn.obter(TABELA, sys_id, "status")["status"] == "success"


def test_runner_que_perdeu_o_item_nao_entra_em_enviando(sn: ServiceNow, criar_itens) -> None:
    # Um runner por fila; se um segundo subir por engano, a conferência antes do Enviar evita a transmissão dupla.
    criar_itens(1)
    primeiro = Fila(sn, FILA_TESTE, frozenset({"enviando"}), runner_id="teste-1")
    item = primeiro.reservar()
    sn.atualizar(TABELA, item.sys_id, {"status": "pending", "locked": "false"})
    segundo = Fila(sn, FILA_TESTE, frozenset({"enviando"}), runner_id="teste-2")
    assert segundo.reservar().sys_id == item.sys_id

    with pytest.raises(ReservaPerdida):
        primeiro.etapa(item, "enviando")
    assert item.etapa != "enviando"


def test_item_devolvido_espera_e_conta_tentativa(sn: ServiceNow, criar_itens) -> None:
    [sys_id] = criar_itens(1)
    fila = Fila(sn, FILA_TESTE, runner_id="teste")
    item = fila.reservar()
    assert item is not None and item.sys_id == sys_id and item.tentativa == 1

    fila.devolver(item, "falha técnica simulada")

    atual = sn.obter(TABELA, sys_id, "status,locked,attempts_count,deferred_till,response_content")
    assert atual["status"] == "pending" and atual["locked"] == "false"
    assert atual["attempts_count"] == "1"
    assert atual["deferred_till"] and atual["response_content"] == "falha técnica simulada"
    assert fila.reservar() is None  # adiado: ainda não volta a ser reservado


def test_falha_de_negocio_registra_tipo_e_mensagem(sn: ServiceNow, criar_itens) -> None:
    [sys_id] = criar_itens(1)
    fila = Fila(sn, FILA_TESTE, runner_id="teste")
    item = fila.reservar()

    fila.falhar(item, "business", "O dígito verificador está inválido.")

    atual = sn.obter(TABELA, sys_id, "status,exception_type,locked,response_content")
    assert atual == {
        "status": "failure",
        "exception_type": "business",
        "locked": "false",
        "response_content": "O dígito verificador está inválido.",
    }


def test_reaper_devolve_item_de_runner_que_caiu(sn: ServiceNow, criar_itens, monkeypatch) -> None:
    [sys_id] = criar_itens(1)
    caiu = Fila(sn, FILA_TESTE, runner_id="teste-caiu")
    item = caiu.reservar()
    caiu.etapa(item, "validando")
    monkeypatch.setattr(config, "LEASE", 0)

    Fila(sn, FILA_TESTE, runner_id="teste-reaper").reaper()

    atual = sn.obter(TABELA, sys_id, "status,locked,remarks")
    assert atual == {"status": "pending", "locked": "false", "remarks": ""}


def test_reaper_nunca_reenfileira_item_que_estava_enviando(sn: ServiceNow, criar_itens, monkeypatch) -> None:
    [sys_id] = criar_itens(1)
    caiu = Fila(sn, FILA_TESTE, frozenset({"enviando"}), runner_id="teste-caiu")
    item = caiu.reservar()
    caiu.etapa(item, "enviando")
    monkeypatch.setattr(config, "LEASE", 0)

    Fila(sn, FILA_TESTE, frozenset({"enviando"}), runner_id="teste-reaper").reaper()

    atual = sn.obter(TABELA, sys_id, "status,exception_type")
    assert atual == {"status": "failure", "exception_type": "application"}


def test_anexo_sobe_e_desce_igual(sn: ServiceNow, criar_itens, tmp_path: Path) -> None:
    [sys_id] = criar_itens(1)
    arquivo = tmp_path / "002-PF-013110-03_GAB112.txt"
    arquivo.write_bytes("linha de teste ção\r\n".encode("latin-1") * 1000)

    sn.anexar(TABELA, sys_id, arquivo)
    [anexo] = sn.anexos(TABELA, sys_id, f"ZZ_YY{TABELA}")
    pasta = tmp_path / "baixado"
    pasta.mkdir()
    baixado = sn.baixar_anexo(anexo, pasta)

    assert anexo["file_name"] == arquivo.name
    assert baixado.read_bytes() == arquivo.read_bytes()
