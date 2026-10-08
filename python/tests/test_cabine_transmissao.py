from pathlib import Path

import pytest

from cabine_transmissao import (
    TABELA_JUD,
    TransmissaoCabineError,
    criar_arquivos_ficticios,
    localizar_arquivos,
    localizar_jud,
    preparar_plano,
    selecionar_linha_requisicao,
)


class FakeServiceNow:
    def __init__(self, registros: list[dict[str, str]]) -> None:
        self.registros = registros
        self.chamadas: list[tuple[str, str, str, int]] = []

    def listar(self, tabela: str, query: str, campos: str, limite: int = 100) -> list[dict[str, str]]:
        self.chamadas.append((tabela, query, campos, limite))
        return self.registros


def _registro(
    *,
    sys_id: str = "jud-1",
    number: str = "JUD0001",
    simba_code: str = "018-PCSP-001316-58",
    official_letter_number: str = "20260730828311099",
) -> dict[str, str]:
    return {
        "sys_id": sys_id,
        "number": number,
        "simba_code": simba_code,
        "official_letter_number": official_letter_number,
    }


def test_localiza_jud_por_simba_e_numero_oficial() -> None:
    sn = FakeServiceNow([_registro()])

    resultado = localizar_jud(sn, "018-PCSP-001316-58", "20260730828311099")

    assert resultado.numero == "JUD0001"
    assert sn.chamadas == [
        (
            TABELA_JUD,
            "simba_code=018-PCSP-001316-58",
            "sys_id,number,simba_code,official_letter_number",
            100,
        )
    ]


def test_rejeita_jud_ambigua_sem_desambiguador() -> None:
    sn = FakeServiceNow([_registro(), _registro(sys_id="jud-2", number="JUD0002")])

    with pytest.raises(TransmissaoCabineError, match="ambígua"):
        localizar_jud(sn, "018-PCSP-001316-58")


def test_localiza_zip_e_pdf_do_atendimento(tmp_path: Path) -> None:
    pasta = tmp_path / "018-PCSP-001316-58"
    pasta.mkdir()
    zip_path = pasta / "018-PCSP-001316-58_GABs.zip"
    pdf_path = pasta / "comprovante.pdf"
    zip_path.write_bytes(b"zip")
    pdf_path.write_bytes(b"pdf")

    resultado = localizar_arquivos(tmp_path, "018-PCSP-001316-58")

    assert resultado.accs100_zip == zip_path
    assert resultado.comprovante_pdf == pdf_path


def test_rejeita_mais_de_um_pdf(tmp_path: Path) -> None:
    pasta = tmp_path / "018-PCSP-001316-58"
    pasta.mkdir()
    (pasta / "caso_GABs.zip").write_bytes(b"zip")
    (pasta / "primeiro.pdf").write_bytes(b"pdf")
    (pasta / "segundo.pdf").write_bytes(b"pdf")

    with pytest.raises(TransmissaoCabineError, match="exatamente um comprovante PDF"):
        localizar_arquivos(tmp_path, "018-PCSP-001316-58")


def test_plano_nunca_permite_confirmacao(tmp_path: Path) -> None:
    pasta = tmp_path / "018-PCSP-001316-58"
    pasta.mkdir()
    (pasta / "caso_GABs.zip").write_bytes(b"zip")
    (pasta / "comprovante.pdf").write_bytes(b"pdf")
    sn = FakeServiceNow([_registro()])

    plano = preparar_plano(
        sn,
        tmp_path,
        "018-PCSP-001316-58",
        "20260730828311099",
    )

    assert plano.confirmar_permitido is False


def test_cria_arquivos_ficticios_para_teste_offline(tmp_path: Path) -> None:
    arquivos = criar_arquivos_ficticios(tmp_path, "018-PCSP-001316-58")

    assert arquivos.accs100_zip.is_file()
    assert arquivos.comprovante_pdf.is_file()
    assert arquivos.accs100_zip.name == "018-PCSP-001316-58_GABs.zip"
    assert arquivos.comprovante_pdf.suffix == ".pdf"


def test_seleciona_linha_por_codigo_e_numero_ccs() -> None:
    linha = {
        "Nº Ctrl Envio": "018-PCSP-001316-58",
        "Num. Ctrl. CCS": "20260730828311099",
    }

    assert selecionar_linha_requisicao(
        [linha],
        "018-PCSP-001316-58",
        "20260730828311099",
    ) == linha


def test_rejeita_linha_sem_numero_ccs_correspondente() -> None:
    with pytest.raises(TransmissaoCabineError, match="Nenhuma requisição"):
        selecionar_linha_requisicao(
            [{"Nº Ctrl Envio": "018-PCSP-001316-58", "Num. Ctrl. CCS": "outro"}],
            "018-PCSP-001316-58",
            "20260730828311099",
        )


def test_rejeita_mais_de_uma_linha_correspondente() -> None:
    linha = {
        "Nº Ctrl Envio": "018-PCSP-001316-58",
        "Num. Ctrl. CCS": "20260730828311099",
    }

    with pytest.raises(TransmissaoCabineError, match="Mais de uma"):
        selecionar_linha_requisicao([linha, linha.copy()], linha["Nº Ctrl Envio"], linha["Num. Ctrl. CCS"])
