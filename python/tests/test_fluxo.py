"""Fluxo completo com o caso fictício 002-PF-013110-03 e arquivos GAB fictícios. Rodar com: pytest -m cadastro"""
import hashlib
import json
from pathlib import Path

import pytest
from gab_ficticio import gerar_gab

from simba import cadastro, fluxo
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
    assert not simba.is_alive()  # Fechar do Passo 3 encerra o Simba
    assert [t.step for t in simba.timings[-2:]] == ["cadastro", "validar_e_gerar"]
    assert all(t.ok and t.attempts == 1 for t in simba.timings[-2:])
