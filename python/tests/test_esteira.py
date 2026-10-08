"""Runner em esteira (processar_lote) com o Simba real e um ServiceNow em memória. Rodar com: pytest -m cadastro

O Transmissor real seleciona cada atendimento; carregar a chave e o Enviar são substituídos (não há chave nesta
máquina e o envio vai para o órgão). Casos fictícios 002-PF-9008NN, arquivados numa pasta temporária.
"""
import json
from pathlib import Path

import pytest
from casos_ficticios import dados_ficticios
from gab_ficticio import gerar_gab
from sn_falso import ServiceNowFalso

from simba import arquivo, config, servicenow, transmissao
from simba.cadastro import Caso
from simba.runner import TABELA_EVIDENCIA, Runner
from simba.servicenow import TABELA_TAREFAS
from simba.transmissao import ResultadoTransmissao

pytestmark = pytest.mark.cadastro

QUANTIDADE = 5


@pytest.fixture
def sn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ServiceNowFalso:
    monkeypatch.setattr(servicenow, "_intervalo", 0)
    monkeypatch.setattr(config, "TRANSMITIR_APOS_VALIDAR", True)
    monkeypatch.setattr(config, "TRABALHO_DIR", tmp_path / "Trabalho")
    monkeypatch.setattr(config, "ARQUIVO_DIR", tmp_path / "Arquivo")
    monkeypatch.setattr(config, "TRANSMITIDOS", tmp_path / "Transmitidos")
    # Reinicia no meio do lote para exercitar o arquivamento dos casos acumulados.
    monkeypatch.setattr(config, "VALIDADOR_REINICIO", 3)
    sn = ServiceNowFalso("Simba Validador")
    for n in range(1, QUANTIDADE + 1):
        dados = dados_ficticios(900800 + n)
        caso = Caso.from_json(dados)
        sn.adicionar_caso(caso, dados, gerar_gab(caso, tmp_path / "gabs" / caso.pasta))

    def enviar_simulado(app, pasta: Path) -> ResultadoTransmissao:
        # O runner precisa ter gravado (e conferido) a etapa "enviando" antes do clique.
        assert [i for i in sn.itens.values() if i["stage"] == "enviando"], "Enviar sem a etapa 'enviando' no SN"
        pasta.mkdir(parents=True, exist_ok=True)
        comprovante = pasta / "comprovante.pdf"
        comprovante.write_bytes(b"%PDF simulado")
        return ResultadoTransmissao("Os arquivos foram transferidos com sucesso (simulado)", pasta, comprovante)

    monkeypatch.setattr(transmissao, "carregar_chave", lambda app, chave, senha: None)
    monkeypatch.setattr(transmissao, "enviar", enviar_simulado)
    monkeypatch.setattr(Runner, "_chave_do_orgao", lambda self, atendimento: (tmp_path / "chave.ASB", "senha-de-teste"))
    return sn


def test_esteira_valida_transmite_e_registra_cada_item(sn: ServiceNowFalso, tmp_path: Path) -> None:
    runner = Runner(sn, ["validador"])

    resumo = runner.processar_lote(QUANTIDADE + 1)

    assert resumo == {"status": "processed", "queue": "validador", "itens": QUANTIDADE}
    for item in sn.itens.values():
        assert item["status"] == "success", item["response_content"]
        assert "transmitido" in item["response_content"]
    for judtask in sn.tarefas:
        assert sn.tarefas[judtask]["evidence_attachment"]
        assert [a["file_name"] for a in sn.anexos_por[(TABELA_EVIDENCIA, judtask)]] == ["comprovante.pdf"]
        nomes = [a["file_name"] for a in sn.anexos_por[(TABELA_TAREFAS, judtask)]]
        assert sum(n.endswith("_saida_simba.zip") for n in nomes) == 1
    # Validador aberto entre os casos: nenhuma etapa precisou de nova tentativa.
    assert all(t.ok and t.attempts == 1 for t in runner.app_validador.timings)
    # Todos os casos saíram do dadosValidador e a pasta de trabalho ficou vazia.
    for item in sn.itens.values():
        atendimento = Caso.from_json(json.loads(item["request_content"])).pasta
        assert not arquivo.dados_validador(atendimento).exists()
        assert (config.ARQUIVO_DIR / atendimento / "envio" / f"{atendimento}.zip").is_file()
    assert not any(config.TRABALHO_DIR.iterdir())
    # Limite de 100 requisições/minuto do usuário de integração: fora o download de cada GAB, ~10 por item.
    sem_downloads = (sum(sn.requisicoes.values()) - sn.requisicoes["baixar_anexo"]) / QUANTIDADE
    print(f"requisições por item, fora os downloads: {sem_downloads:.1f} {dict(sn.requisicoes)}")
    assert sem_downloads <= 10


def test_itens_ja_transmitidos_sao_concluidos_sem_abrir_o_simba(sn: ServiceNowFalso) -> None:
    for item in sn.itens.values():
        sn._guardar(TABELA_EVIDENCIA, json.loads(item["request_content"])["Judtask"], Path(__file__))
    runner = Runner(sn, ["validador"])

    resumo = runner.processar_lote(QUANTIDADE)

    assert resumo["status"] == "empty"
    for item in sn.itens.values():
        assert item["status"] == "success"
        assert "não reenviado" in item["response_content"]
        assert item["stage"] != "enviando"
    assert runner.app_validador.timings == []
