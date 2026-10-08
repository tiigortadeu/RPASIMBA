"""Executa o fluxo Python de teste da resposta na Cabine CCS-JUD.

O fluxo termina depois de navegar pelos arquivos. Nunca existe chamada para
Confirmar. A seleção por índice é permitida somente com ``--row-index``,
porque a grade nativa ainda não expõe suas células para leitura estruturada.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cabine_jd import navegar
from cabine_ui import CabineUIError, CabineUIDriver


def executar(
    simba_code: str,
    official_letter_number: str,
    row_index: int,
    accs100: Path,
    comprovante: Path,
) -> None:
    if not simba_code.strip():
        raise ValueError("simba_code não pode ficar vazio")
    if not official_letter_number.strip():
        raise ValueError("official_letter_number não pode ficar vazio")

    hwnd = navegar()
    driver = CabineUIDriver(hwnd)
    resposta_reutilizada = driver.tem_resposta_aberta()
    if not resposta_reutilizada:
        driver.selecionar_requisicao()
        driver.pesquisar(simba_code)
        driver.selecionar_linha_por_indice_teste(row_index)
        driver.clicar_responder()
    else:
        driver.selecionar_atendimento_requisicao()
    driver.selecionar_arquivo(str(accs100), "ACCS100")
    driver.selecionar_arquivo(str(comprovante), "Comprovante Simba")
    print(
        f"Fluxo concluído até os arquivos: simba_code={simba_code}; "
        f"official_letter_number={official_letter_number}; row_index={row_index}"
    )
    print("Confirmar não foi chamado.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simba-code", required=True)
    parser.add_argument("--official-letter-number", required=True)
    parser.add_argument(
        "--row-index",
        required=True,
        type=int,
        help="índice da linha observado no teste; 0 é a primeira linha",
    )
    parser.add_argument("--accs100", required=True, type=Path)
    parser.add_argument("--comprovante", required=True, type=Path)
    args = parser.parse_args()

    try:
        executar(
            args.simba_code,
            args.official_letter_number,
            args.row_index,
            args.accs100,
            args.comprovante,
        )
    except (CabineUIError, FileNotFoundError, TimeoutError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
