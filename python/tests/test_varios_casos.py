"""Vários casos diferentes em sequência no Simba real, arquivando cada um para a lista do Validador não crescer.

Rodar com: pytest -m cadastro tests/test_varios_casos.py   (SIMBA_TESTE_CASOS=N muda a quantidade; padrão 10)
Cria atendimentos fictícios 002-PF-9000NN-DV no dadosValidador e os move para uma pasta temporária.
"""
import os
from pathlib import Path

import pytest
from casos_ficticios import caso_ficticio, dv_atendimento
from gab_ficticio import ENDERECO_ACENTUADO, crlf, gerar_gab, gravar_gab, linhas_gab112

from simba import arquivo, fluxo, screens
from simba.app import SimbaApp

QUANTIDADE = int(os.environ.get("SIMBA_TESTE_CASOS", "10"))


def test_dv_bate_com_os_casos_conhecidos() -> None:
    assert dv_atendimento("002", "013110") == "03"
    assert dv_atendimento("001", "006638") == "18"


def _lista_passo1(simba: SimbaApp) -> list[str]:
    def ler(app: SimbaApp) -> list[str]:
        lista = app.control(screens.PASSO_1, "Atendimento a Validar")
        return [e.name for _, e in lista.walk() if e is not lista]

    return simba.run_step("ler_lista_passo1", ler)


@pytest.mark.cadastro
def test_processa_varios_casos_e_arquiva_cada_um(simba: SimbaApp, tmp_path: Path) -> None:
    arquivados = tmp_path / "arquivo"
    # O fixture é da sessão: só contam os passos deste teste (outros testes têm casos negativos esperados).
    inicio = len(simba.timings)
    antes = _lista_passo1(simba)
    casos = [caso_ficticio(900000 + n) for n in range(1, QUANTIDADE + 1)]

    for n, caso in enumerate(casos):
        if n % 2:
            # Metade dos casos vem com o defeito real mais comum (UTF-8 com "ª"), corrigido automaticamente.
            linhas = linhas_gab112(caso, endereco=ENDERECO_ACENTUADO)
            pasta = gravar_gab(caso, tmp_path / caso.pasta, crlf(linhas).encode("utf-8"))
        else:
            pasta = gerar_gab(caso, tmp_path / caso.pasta)

        resultado = fluxo.processar(simba, caso, pasta)

        assert resultado.pacote.is_file()
        assert bool(resultado.correcoes) == bool(n % 2)
        # O Validador volta ao Passo 1 aberto e mantém arquivos do caso em uso: só dá para arquivar fechado.
        simba.kill()
        destino = arquivo.arquivar_atendimento(caso.pasta, arquivados)
        assert destino == arquivados / caso.pasta
        assert (destino / "envio" / f"{caso.pasta}.zip").is_file()
        assert not arquivo.dados_validador(caso.pasta).exists()

    # Nenhum caso processado ficou na lista suspensa do Validador.
    depois = _lista_passo1(simba)
    assert not {c.pasta for c in casos} & set(depois)
    assert len(depois) <= len(antes)
    assert all(t.ok for t in simba.timings[inicio:])
