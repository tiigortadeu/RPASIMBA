r"""Executa o E2E local do Simba sem enviar e sem confirmar na Cabine.

Uso no CMD:
    .venv\Scripts\python testar_e2e_local.py

O script cadastra/valida/gera no Validador, prepara o Transmissor até
habilitar ``Enviar`` e navega na Cabine até os arquivos. Nenhum clique em
``Enviar`` ou ``Confirmar`` existe neste fluxo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


PYTHON_DIR = Path(__file__).resolve().parent


def argumento_caminho(parser: argparse.ArgumentParser, valor: str | None, variavel: str) -> Path:
    if not valor:
        parser.error(f"Informe o caminho pelo argumento ou por {variavel} no .env")
    caminho = Path(valor).expanduser()
    if not caminho.exists():
        parser.error(f"Caminho não encontrado: {caminho}")
    return caminho


def executar(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(PYTHON_DIR))

    from cabine_rpa import executar as executar_cabine
    from simba import arquivo, config, fluxo, transmissao
    from simba.app import SimbaApp, TRANSMISSOR, VALIDADOR
    from simba.cadastro import Caso

    # O import de simba.config carrega o .env.
    mock_dir = argumento_caminho(args.parser, args.mock_dir or os.environ.get("SIMBA_MOCK_DIR"), "SIMBA_MOCK_DIR")
    dados = json.loads((mock_dir / "content.txt.txt").read_text(encoding="utf-8"))
    caso = Caso.from_json(dados)
    print(f"[1/3] Caso: {caso.pasta}")

    validador = SimbaApp(VALIDADOR)
    resultado = fluxo.processar(validador, caso, mock_dir)
    print(f"[1/3] Validador OK: {resultado.pacote}")
    print(f"[1/3] Hash: {resultado.hash}")

    arquivo.sincronizar_transmissor(caso.pasta)
    print(f"[2/3] Caso disponível no Transmissor: {arquivo.dados_transmissor(caso.pasta)}")

    transmissor = SimbaApp(TRANSMISSOR)
    transmissor.ensure_ready()
    transmissao.selecionar_atendimento(transmissor, caso.pasta)
    senha = (mock_dir / "senha_chave.txt.txt").read_text(encoding="utf-8").strip()
    transmissao.carregar_chave(transmissor, mock_dir / "CHAVE 002.ASB", senha)
    print("[2/3] Transmissor OK: Enviar habilitado; nenhum clique em Enviar.")

    pasta_transmitidos = config.TRANSMITIDOS / caso.pasta
    accs100 = pasta_transmitidos / f"{caso.pasta}_GABs.zip"
    if not accs100.is_file():
        pasta_transmitidos.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resultado.pacote, accs100)

    comprovante = argumento_caminho(
        args.parser, args.comprovante or os.environ.get("CABINE_COMPROVANTE_TESTE"), "CABINE_COMPROVANTE_TESTE"
    )
    executar_cabine(
        caso.pasta,
        str(dados.get("Número do Ofício", "20260730828311099")),
        args.row_index,
        accs100,
        comprovante,
    )
    print("[3/3] Cabine OK: navegação e seleção executadas; nenhum clique em Confirmar.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-dir", help="pasta com content.txt.txt, GABs, chave e senha (padrão: SIMBA_MOCK_DIR)")
    parser.add_argument("--comprovante", help="PDF usado na seleção da Cabine (padrão: CABINE_COMPROVANTE_TESTE)")
    parser.add_argument("--row-index", type=int, default=0)
    parser.set_defaults(parser=parser)
    args = parser.parse_args()
    executar(args)


if __name__ == "__main__":
    main()
