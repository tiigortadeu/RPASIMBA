"""Fluxo completo com o caso fictício 002-PF-013110-03 e arquivos GAB fictícios. Rodar com: pytest -m cadastro"""
import hashlib
import json
from pathlib import Path

import pytest
from gab_ficticio import DEFEITOS_CORRIGIVEIS, ENDERECO_ACENTUADO, crlf, gerar_gab, gravar_gab, linhas_gab112

from simba import cadastro, fluxo, screens, validacao
from simba.app import SimbaApp

pytestmark = pytest.mark.cadastro

DADOS = Path(__file__).parent / "data" / "caso_teste.json"


def test_processa_caso_do_cadastro_ao_pacote_de_envio(simba: SimbaApp, tmp_path: Path) -> None:
    caso = cadastro.Caso.from_json(json.loads(DADOS.read_text(encoding="utf-8")))
    pasta = gerar_gab(caso, tmp_path)

    resultado = fluxo.processar(simba, caso, pasta)

    assert resultado.pacote.name == f"{caso.pasta}.zip"
    # O Simba exibe o MD5 sem zeros à esquerda.
    assert int(resultado.hash, 16) == int(hashlib.md5(resultado.pacote.read_bytes()).hexdigest(), 16)
    assert (resultado.pacote.parent / f"{caso.pasta}.zip.hash").read_text().split("\t")[-1].strip() == resultado.hash
    assert simba.is_open(screens.PASSO_1)  # volta ao Passo 1 para o próximo caso, sem fechar
    assert [t.step for t in simba.timings[-2:]] == ["cadastro", "validar_e_gerar"]
    assert all(t.ok and t.attempts == 1 for t in simba.timings[-2:])
    assert resultado.correcoes == []


@pytest.mark.parametrize("defeito", DEFEITOS_CORRIGIVEIS)
def test_gab_com_defeito_conhecido_e_corrigido_e_aprovado(simba: SimbaApp, tmp_path: Path, defeito: str) -> None:
    caso = cadastro.Caso.from_json(json.loads(DADOS.read_text(encoding="utf-8")))
    linhas = linhas_gab112(caso, endereco=ENDERECO_ACENTUADO)
    pasta = gravar_gab(caso, tmp_path, DEFEITOS_CORRIGIVEIS[defeito](linhas))

    resultado = fluxo.processar(simba, caso, pasta)

    assert resultado.correcoes, "o Simba aprovou o arquivo defeituoso sem correção"
    assert resultado.pacote.is_file()
    assert (pasta / f"{caso.pasta}_GAB112.txt").read_bytes() == crlf(linhas).encode("cp1252")
    assert simba.timings[-1].ok and simba.timings[-1].attempts == 1


def test_erro_que_nao_sabe_corrigir_continua_reprovando(simba: SimbaApp, tmp_path: Path) -> None:
    caso = cadastro.Caso.from_json(json.loads(DADOS.read_text(encoding="utf-8")))
    linhas = linhas_gab112(caso, endereco=ENDERECO_ACENTUADO)[:-1]  # falta um investigado no GAB112
    pasta = gravar_gab(caso, tmp_path, crlf(linhas).encode("utf-8"))

    with pytest.raises(validacao.ArquivosReprovados) as reprovado:
        fluxo.processar(simba, caso, pasta)

    # A codificação foi corrigida, mas o investigado ausente é erro de dados: volta para o usuário.
    assert "não foi encontrado no arquivo cadastral" in reprovado.value.message
    assert "Correções automáticas aplicadas antes desta validação" in reprovado.value.message
    assert "convertido de UTF-8" in reprovado.value.message
