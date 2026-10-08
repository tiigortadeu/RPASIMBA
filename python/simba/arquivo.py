"""Tira atendimentos já processados do dadosValidador, movendo-os para a pasta de arquivo.

O Validador lista no Passo 1 (e o Transmissor na tela principal) todo atendimento que está em dadosValidador.
Com milhares de casos, a lista cresceria sem fim: cada caso é movido para SIMBA_ARQUIVO assim que termina,
com sucesso ou falha (a pasta arquivada serve para análise manual). O Simba precisa estar fechado.

Cada programa lê o dadosValidador ao lado da sua pasta de instalação. Quando Validador e Transmissor estão
instalados em pastas irmãs (ex.: Validador\5.8.7 e Transmissor\4.6.7), cada um tem o seu dadosValidador e o
atendimento gerado pelo Validador precisa ser copiado para o do Transmissor antes de transmitir.
"""
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from simba import config

log = logging.getLogger(__name__)


def dados_validador(atendimento: str) -> Path:
    return config.SIMBA_VALIDADOR_DADOS / atendimento


def dados_transmissor(atendimento: str) -> Path:
    return config.SIMBA_TRANSMISSOR_DADOS / atendimento


def dados_compartilhados() -> bool:
    return config.SIMBA_VALIDADOR_DADOS.resolve() == config.SIMBA_TRANSMISSOR_DADOS.resolve()


def sincronizar_transmissor(atendimento: str) -> None:
    """Copia o atendimento do dadosValidador do Validador para o do Transmissor (substitui uma cópia anterior)."""
    if dados_compartilhados():
        return
    origem = dados_validador(atendimento)
    if not origem.is_dir():
        raise FileNotFoundError(f"Dados do Validador não encontrados: {origem}")
    destino = dados_transmissor(atendimento)
    if destino.exists():
        shutil.rmtree(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(origem, destino)
    log.info("%s copiado para o dadosValidador do Transmissor (%s)", atendimento, destino)


def _mover(origem: Path, base: Path, atendimento: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    destino = base / atendimento
    if destino.exists():
        destino = base / f"{atendimento}_{datetime.now():%Y%m%d-%H%M%S}"
    shutil.move(str(origem), str(destino))
    log.info("%s arquivado em %s", atendimento, destino)
    return destino


def arquivar_atendimento(atendimento: str, base: Optional[Path] = None) -> Optional[Path]:
    """Move dadosValidador/<atendimento> para <base>/<atendimento>; None se não houver o que mover.

    Se o atendimento já foi arquivado antes (reprocessamento), a nova cópia ganha um sufixo de data e hora.
    A cópia do Transmissor (quando ele tem dadosValidador próprio) vai para <base>/Transmissor/<atendimento>.
    """
    base = base or config.ARQUIVO_DIR
    destino = None
    if not dados_compartilhados() and dados_transmissor(atendimento).exists():
        destino = _mover(dados_transmissor(atendimento), base / "Transmissor", atendimento)
    if dados_validador(atendimento).exists():
        destino = _mover(dados_validador(atendimento), base, atendimento)
    return destino
