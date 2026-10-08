"""Preparação segura da resposta de uma requisição na Cabine CCS-JUD.

Esta etapa resolve a JUD no ServiceNow, localiza os arquivos produzidos pelo
Simba e devolve um plano para a automação da Cabine. O plano termina antes de
qualquer confirmação ou envio.
"""

from __future__ import annotations

import argparse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from simba import config
from simba.servicenow import ServiceNow


TABELA_JUD = "x_xpi_ofj_judicial_office"


class TransmissaoCabineError(RuntimeError):
    """Falha que impede identificar uma transmissão de forma inequívoca."""


class JudClient(Protocol):
    def listar(self, tabela: str, query: str, campos: str, limite: int = 100) -> list[dict[str, str]]:
        ...


@dataclass(frozen=True)
class JudParaTransmissao:
    sys_id: str
    numero: str
    simba_code: str
    official_letter_number: str


@dataclass(frozen=True)
class ArquivosTransmissao:
    accs100_zip: Path
    comprovante_pdf: Path


@dataclass(frozen=True)
class PlanoTransmissaoCabine:
    jud: JudParaTransmissao
    arquivos: ArquivosTransmissao
    confirmar_permitido: bool = False


def selecionar_linha_requisicao(
    linhas: list[dict[str, str]],
    simba_code: str,
    official_letter_number: str,
) -> dict[str, str]:
    """Retorna uma única linha compatível ou falha fechado."""
    codigo = _obrigatorio(simba_code, "simba_code")
    oficial = _obrigatorio(official_letter_number, "official_letter_number")
    candidatos = [
        linha
        for linha in linhas
        if _texto(linha.get("Nº Ctrl Envio")) == codigo
        and _texto(linha.get("Num. Ctrl. CCS")) == oficial
    ]
    if not candidatos:
        raise TransmissaoCabineError(
            f"Nenhuma requisição corresponde a simba_code={codigo} e "
            f"official_letter_number={oficial}"
        )
    if len(candidatos) > 1:
        raise TransmissaoCabineError(
            f"Mais de uma requisição corresponde a simba_code={codigo} e "
            f"official_letter_number={oficial}"
        )
    return candidatos[0]


def localizar_jud(
    sn: JudClient,
    simba_code: str,
    official_letter_number: str | None = None,
) -> JudParaTransmissao:
    """Encontra uma única JUD, usando o número oficial para desambiguar."""
    codigo = _obrigatorio(simba_code, "simba_code")
    query = f"simba_code={codigo}"
    registros = sn.listar(
        TABELA_JUD,
        query,
        "sys_id,number,simba_code,official_letter_number",
        limite=100,
    )
    if not registros:
        raise TransmissaoCabineError(f"Nenhuma JUD encontrada para simba_code={codigo}")

    candidatos = registros
    if official_letter_number is not None:
        oficial = _obrigatorio(official_letter_number, "official_letter_number")
        candidatos = [
            registro
            for registro in registros
            if _texto(registro.get("official_letter_number")) == oficial
        ]
        if not candidatos:
            raise TransmissaoCabineError(
                f"Nenhuma JUD com simba_code={codigo} e "
                f"official_letter_number={oficial}"
            )

    if len(candidatos) != 1:
        numeros = ", ".join(_texto(registro.get("number")) or "<sem número>" for registro in candidatos)
        raise TransmissaoCabineError(
            f"JUD ambígua para simba_code={codigo}; candidatos: {numeros}. "
            "Informe official_letter_number."
        )

    registro = candidatos[0]
    return JudParaTransmissao(
        sys_id=_campo_obrigatorio(registro, "sys_id"),
        numero=_campo_obrigatorio(registro, "number"),
        simba_code=_campo_obrigatorio(registro, "simba_code"),
        official_letter_number=_campo_obrigatorio(registro, "official_letter_number"),
    )


def localizar_arquivos(transmitidos: Path, atendimento: str) -> ArquivosTransmissao:
    """Localiza exatamente um ZIP ACCS100 e um comprovante PDF do atendimento."""
    atendimento = _obrigatorio(atendimento, "atendimento")
    pasta = transmitidos / atendimento
    if not pasta.is_dir():
        raise TransmissaoCabineError(f"Pasta de transmissão não encontrada: {pasta}")

    zips = sorted(pasta.glob("*_GABs.zip"))
    pdfs = sorted(pasta.glob("*.pdf"))
    if len(zips) != 1:
        raise TransmissaoCabineError(
            f"Esperado exatamente um ZIP *_GABs.zip em {pasta}; encontrados {len(zips)}"
        )
    if len(pdfs) != 1:
        raise TransmissaoCabineError(
            f"Esperado exatamente um comprovante PDF em {pasta}; encontrados {len(pdfs)}"
        )
    return ArquivosTransmissao(accs100_zip=zips[0], comprovante_pdf=pdfs[0])


def preparar_plano(
    sn: ServiceNow,
    transmitidos: Path,
    simba_code: str,
    official_letter_number: str,
) -> PlanoTransmissaoCabine:
    """Resolve a JUD e os anexos sem clicar ou alterar qualquer registro."""
    jud = localizar_jud(sn, simba_code, official_letter_number)
    arquivos = localizar_arquivos(transmitidos, jud.simba_code)
    return PlanoTransmissaoCabine(jud=jud, arquivos=arquivos)


def criar_arquivos_ficticios(transmitidos: Path, atendimento: str) -> ArquivosTransmissao:
    """Cria um ZIP ACCS100 e um PDF mínimo para teste offline da Cabine."""
    atendimento = _obrigatorio(atendimento, "atendimento")
    pasta = transmitidos / atendimento
    pasta.mkdir(parents=True, exist_ok=True)
    zip_path = pasta / f"{atendimento}_GABs.zip"
    pdf_path = pasta / f"{atendimento}_comprovante.pdf"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as pacote:
        pacote.writestr(f"{atendimento}_GAB109.txt", "ARQUIVO FICTICIO DE TESTE\n")
        pacote.writestr(f"{atendimento}_GAB112.txt", "ARQUIVO FICTICIO DE TESTE\n")

    pdf_path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    return ArquivosTransmissao(accs100_zip=zip_path, comprovante_pdf=pdf_path)


def _texto(valor: str | None) -> str:
    return (valor or "").strip()


def _obrigatorio(valor: str | None, campo: str) -> str:
    resultado = _texto(valor)
    if not resultado:
        raise TransmissaoCabineError(f"{campo} não pode ficar vazio")
    return resultado


def _campo_obrigatorio(registro: dict[str, str], campo: str) -> str:
    return _obrigatorio(registro.get(campo), campo)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simba-code", required=True, help="Código de envio da JUD")
    parser.add_argument("--official-letter-number", required=True, help="Num. Ctrl. CCS da JUD")
    parser.add_argument(
        "--transmitidos",
        type=Path,
        default=config.TRANSMITIDOS,
        help="Pasta que contém Transmitidos/<atendimento>",
    )
    parser.add_argument(
        "--navegar",
        action="store_true",
        help="Abre a Cabine e navega até a requisição, sem selecionar ou responder",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Cria ZIP/PDF fictícios e não consulta o ServiceNow",
    )
    args = parser.parse_args()

    if args.fake:
        arquivos = criar_arquivos_ficticios(args.transmitidos, args.simba_code)
        print(f"Modo offline: arquivos fictícios criados para {args.simba_code}")
        print(f"ACCS100: {arquivos.accs100_zip}")
        print(f"Comprovante Simba: {arquivos.comprovante_pdf}")
    else:
        if not (config.SN_INSTANCIA and config.SN_USUARIO and config.SN_SENHA):
            parser.error("defina SN_INSTANCIA, SN_USUARIO e SN_SENHA (python/.env)")
        sn = ServiceNow(config.SN_INSTANCIA, config.SN_USUARIO, config.SN_SENHA)
        plano = preparar_plano(
            sn,
            args.transmitidos,
            args.simba_code,
            args.official_letter_number,
        )
        print(f"JUD: {plano.jud.numero} ({plano.jud.sys_id})")
        print(f"Num. Ctrl. CCS: {plano.jud.official_letter_number}")
        print(f"ACCS100: {plano.arquivos.accs100_zip}")
        print(f"Comprovante Simba: {plano.arquivos.comprovante_pdf}")
    print("Execução limitada: não selecionar, responder ou confirmar.")

    if args.navegar:
        from cabine_jd import navegar

        navegar()
        print("Cabine posicionada na tela de requisição; nenhuma requisição foi selecionada.")


if __name__ == "__main__":
    main()
