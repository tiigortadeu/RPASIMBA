"""Teste integrado local, sem transmissão, do Simba até os comprovantes da Cabine.

O Validador Simba real é exercitado pelo teste existente ``tests/test_fluxo.py``.
Este script exercita a etapa seguinte offline: cria os arquivos de saída fictícios,
resolve uma JUD mockada e executa o fluxo da Cabine com UI mockada até selecionar os
dois comprovantes. Nenhuma chamada ``Confirmar`` ou transmissão é feita.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cabine_transmissao import criar_arquivos_ficticios, preparar_plano
from cabine_rpa import executar


class FakeServiceNow:
    def __init__(self, registros: list[dict[str, str]]) -> None:
        self.registros = registros

    def listar(self, tabela: str, query: str, campos: str, limite: int = 100) -> list[dict[str, str]]:
        return self.registros


class FakeCabineDriver:
    chamadas: list[tuple[str, object]] = []

    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd
        self.chamadas.append(("driver", hwnd))

    def selecionar_requisicao(self) -> None:
        self.chamadas.append(("selecionar_requisicao", None))

    def tem_resposta_aberta(self) -> bool:
        return False

    def pesquisar(self, simba_code: str) -> None:
        self.chamadas.append(("pesquisar", simba_code))

    def selecionar_linha_por_indice_teste(self, row_index: int) -> None:
        self.chamadas.append(("selecionar_linha", row_index))

    def clicar_responder(self) -> None:
        self.chamadas.append(("responder", None))
        self.selecionar_atendimento_requisicao()

    def selecionar_atendimento_requisicao(self) -> None:
        self.chamadas.append(("selecionar_atendimento_requisicao", None))

    def selecionar_arquivo(self, caminho: str, finalidade: str) -> None:
        self.chamadas.append(("selecionar_arquivo", finalidade, Path(caminho)))


def executar_teste() -> None:
    simba_code = "018-PCSP-001316-58"
    official_letter_number = "20260730828311099"

    with TemporaryDirectory(prefix="rpasimba-fluxo-") as pasta_temporaria:
        transmitidos = Path(pasta_temporaria) / "Transmitidos"
        arquivos = criar_arquivos_ficticios(transmitidos, simba_code)
        sn = FakeServiceNow(
            [
                {
                    "sys_id": "jud-mock-1",
                    "number": "JUD-MOCK-0001",
                    "simba_code": simba_code,
                    "official_letter_number": official_letter_number,
                }
            ]
        )
        plano = preparar_plano(sn, transmitidos, simba_code, official_letter_number)

        FakeCabineDriver.chamadas = []
        with (
            patch("cabine_rpa.navegar", return_value=1234) as navegar,
            patch("cabine_rpa.CabineUIDriver", FakeCabineDriver),
        ):
            executar(
                simba_code,
                official_letter_number,
                row_index=0,
                accs100=plano.arquivos.accs100_zip,
                comprovante=plano.arquivos.comprovante_pdf,
            )

        assert navegar.call_count == 1
        assert ("selecionar_requisicao", None) in FakeCabineDriver.chamadas
        assert ("pesquisar", simba_code) in FakeCabineDriver.chamadas
        assert ("selecionar_linha", 0) in FakeCabineDriver.chamadas
        assert ("responder", None) in FakeCabineDriver.chamadas
        selecionados = [
            chamada
            for chamada in FakeCabineDriver.chamadas
            if chamada[0] == "selecionar_arquivo"
        ]
        assert [chamada[1] for chamada in selecionados] == ["ACCS100", "Comprovante Simba"]
        assert all(Path(chamada[2]).is_file() for chamada in selecionados)

        print(f"JUD mockada: {plano.jud.numero}")
        print(f"ACCS100: {arquivos.accs100_zip}")
        print(f"Comprovante Simba: {arquivos.comprovante_pdf}")
        print("Fluxo offline concluído até selecionar os comprovantes.")
        print("Confirmar e transmissão não foram chamados.")


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    executar_teste()


if __name__ == "__main__":
    main()
