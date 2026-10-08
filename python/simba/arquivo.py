"""Tira atendimentos já processados do dadosValidador, movendo-os para a pasta de arquivo.

O Validador lista no Passo 1 (e o Transmissor na tela principal) todo atendimento que está em dadosValidador.
Com milhares de casos, a lista cresceria sem fim: cada caso é movido para SIMBA_ARQUIVO assim que termina,
com sucesso ou falha (a pasta arquivada serve para análise manual). O Simba precisa estar fechado.
"""
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from simba import config

log = logging.getLogger(__name__)


def dados_validador(atendimento: str) -> Path:
    return config.SIMBA_HOME / "dadosValidador" / atendimento


def arquivar_atendimento(atendimento: str, base: Optional[Path] = None) -> Optional[Path]:
    """Move dadosValidador/<atendimento> para <base>/<atendimento>; None se não houver o que mover.

    Se o atendimento já foi arquivado antes (reprocessamento), a nova cópia ganha um sufixo de data e hora.
    """
    origem = dados_validador(atendimento)
    if not origem.exists():
        return None
    base = base or config.ARQUIVO_DIR
    base.mkdir(parents=True, exist_ok=True)
    destino = base / atendimento
    if destino.exists():
        destino = base / f"{atendimento}_{datetime.now():%Y%m%d-%H%M%S}"
    shutil.move(str(origem), str(destino))
    log.info("%s arquivado em %s", atendimento, destino)
    return destino
