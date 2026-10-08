"""Comentário gravado na JUDTASK quando um work item para (sem ServiceNow: só o conteúdo e a origem da JUDTASK)."""
import json

from simba import notificacao
from simba.servicenow import ServiceNow

# Sem rede: estes caminhos não fazem chamadas ao SN.
SN = ServiceNow("instancia-de-teste", "usuario", "senha")


def _parada(**campos) -> notificacao.Parada:
    base = dict(
        processo="Simba Validador",
        work_item="SimbaValidador_JUDTASK0032589",
        etapa="validando",
        tentativa=1,
        orientacao=notificacao.NEGOCIO,
        erro="O dígito verificador está inválido.",
        runner="vm01-rpa",
    )
    base.update(campos)
    return notificacao.Parada(**base)


def test_erro_de_validacao_diz_onde_parou_o_erro_e_o_que_fazer() -> None:
    texto = notificacao.montar_comentario(_parada(detalhe="último passo no Simba: cadastro (falhou após 1 tentativa(s))"))

    assert texto.splitlines() == [
        "[RPA Simba Validador] Erro de validação/dados",
        "Parou em: cadastro e validação no Simba Validador",
        "Erro: O dígito verificador está inválido.",
        "Detalhe: último passo no Simba: cadastro (falhou após 1 tentativa(s))",
        "O que fazer: Corrija os dados ou os arquivos da tarefa e reenvie para o RPA. O RPA não tentará de novo sozinho.",
        "Work item: SimbaValidador_JUDTASK0032589 | tentativa 1 | runner vm01-rpa",
    ]


def test_falha_na_transmissao_pede_tratamento_manual() -> None:
    texto = notificacao.montar_comentario(
        _parada(processo="Simba Transmissor", etapa="enviando", orientacao=notificacao.MANUAL, erro="Timeout")
    )

    assert "Parou em: transmissão pelo Simba Transmissor" in texto
    assert "Verifique e trate manualmente" in texto
    assert "Detalhe" not in texto


def test_etapa_desconhecida_aparece_pelo_nome() -> None:
    assert "Parou em: outra" in notificacao.montar_comentario(_parada(etapa="outra"))
    assert "Parou em: desconhecido" in notificacao.montar_comentario(_parada(etapa=""))


def test_judtask_vem_do_json_do_work_item() -> None:
    request = json.dumps({"Judtask": "589730519715b2146509fd56f053afcc", "Simba": "001-MPF-006638-18"})

    assert notificacao.resolver_judtask(SN, "SimbaTransmissor_JUDTASK0032590", request) == (
        "589730519715b2146509fd56f053afcc"
    )


def test_sem_json_e_sem_numero_de_tarefa_no_nome_nao_ha_judtask() -> None:
    assert notificacao.resolver_judtask(SN, "Subida Arquivo 25/03/2026", "não é json") is None
