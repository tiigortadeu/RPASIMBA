"""Passo 3: gera o pacote de envio (zip + hash) de um atendimento com arquivos aprovados no Passo 2."""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from simba import config, screens
from simba.app import SimbaApp
from simba.jab import wait_for

P3 = screens.PASSO_3


@dataclass
class ResultadoGeracao:
    hash: str
    pacote: Path
    # Correções automáticas aplicadas aos arquivos antes da validação aprovada (simba.correcao).
    correcoes: list[str] = field(default_factory=list)


def abrir_passo3(app: SimbaApp, atendimento: str) -> None:
    """Continuar >> no Passo 2 (que precisa estar aprovado)."""
    app.control(screens.PASSO_2, "Continuar").press()
    app.expect(P3)
    exibido = app.control(P3, "Atendimento").name
    if exibido != atendimento:
        raise AssertionError(f"Passo 3 abriu para {exibido!r}, esperado {atendimento!r}")


def gerar(app: SimbaApp, atendimento: str) -> ResultadoGeracao:
    """Gerar -> espera o código hash e confere com o MD5 do zip gerado em dadosValidador/<atendimento>/envio."""
    app.control(P3, "Gerar").press()
    rotulo = app.control(P3, "Hash")

    def hash_exibido() -> Optional[str]:
        # O rótulo vem como "hash\t<md5>".
        texto = rotulo.refresh().name
        return texto.split("\t")[-1].strip() if texto.startswith("hash") else None

    codigo = app.expect_value(hash_exibido, config.SCREEN_TIMEOUT, "código hash do Passo 3")
    pacote = config.SIMBA_HOME / "dadosValidador" / atendimento / "envio" / f"{atendimento}.zip"
    md5 = hashlib.md5(pacote.read_bytes()).hexdigest()
    # O Simba exibe o MD5 sem zeros à esquerda (ex.: "cf28..." para "0cf28..."); compara pelo valor.
    if int(md5, 16) != int(codigo, 16):
        raise AssertionError(f"Hash exibido ({codigo}) difere do MD5 de {pacote} ({md5})")
    return ResultadoGeracao(codigo, pacote)


def fechar(app: SimbaApp) -> None:
    """Fechar no Passo 3 encerra o Simba; espera o processo sair."""
    app.control(P3, "Fechar").press()
    wait_for(lambda: not app.is_alive(), config.SCREEN_TIMEOUT, "Simba encerrar após Fechar")
