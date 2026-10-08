"""Modo simulação: o runner roda de verdade com itens reais, sem gravar nada no ServiceNow e sem enviar.

Leituras (fila, JUDTASK, anexos, GABs) vão para a instância do .env, no limite SN_REQUISICOES_POR_MINUTO.
Gravações (reserva, etapa, anexos de saída, comprovante, conclusão) ficam só em memória, mas contam no limite
como se fossem feitas, para medir o ritmo real; leituras seguintes do mesmo registro enxergam essas gravações.
O Validador roda de verdade; o Transmissor seleciona o atendimento e, se o órgão tiver chave no CSV, carrega a
chave de verdade (Selecionar..., arquivo, senha) até o Enviar habilitar. Sem chave configurada, essa parte é pulada.
O Enviar é sempre simulado (nunca há clique). Comprovantes simulados e casos arquivados vão para uma pasta própria.
"""
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from simba import config, servicenow, transmissao
from simba.fila import TABELA
from simba.servicenow import ServiceNow
from simba.transmissao import ResultadoTransmissao

log = logging.getLogger(__name__)

CHAVE_SIMULADA = "chave_simulada.ASB"


class ServiceNowSomenteLeitura(ServiceNow):
    """Lê da instância real; grava só em memória (e sobrepõe essas gravações nas leituras seguintes)."""

    def __init__(self, instancia: str, usuario: str, senha: str) -> None:
        super().__init__(instancia, usuario, senha)
        self.gravado: dict[tuple[str, str], dict[str, str]] = {}
        self.anexados: list[tuple[str, str, str]] = []
        self.requisicoes: Counter[str] = Counter()

    def _simular(self, tipo: str) -> None:
        servicenow._cadenciar()
        self.requisicoes[tipo] += 1

    def listar(self, tabela: str, query: str, campos: str, limite: int = 100) -> list[dict[str, str]]:
        self.requisicoes["listar"] += 1
        registros = super().listar(tabela, query, campos, limite)
        return [{**r, **self.gravado.get((tabela, r.get("sys_id", "")), {})} for r in registros]

    def obter(self, tabela: str, sys_id: str, campos: str) -> dict[str, str]:
        self.requisicoes["obter"] += 1
        return {**super().obter(tabela, sys_id, campos), **self.gravado.get((tabela, sys_id), {})}

    def anexos(self, tabela: str, sys_id: str, *outras_tabelas: str) -> list[dict[str, str]]:
        self.requisicoes["anexos"] += 1
        return super().anexos(tabela, sys_id, *outras_tabelas)

    def baixar_anexo(self, anexo: dict[str, str], pasta: Path) -> Path:
        self.requisicoes["baixar_anexo"] += 1
        return super().baixar_anexo(anexo, pasta)

    def atualizar(self, tabela: str, sys_id: str, valores: dict[str, Any], campos: str = "sys_id") -> dict[str, str]:
        self._simular(f"atualizar {'item' if tabela == TABELA else 'tarefa'} (simulado)")
        self.gravado.setdefault((tabela, sys_id), {}).update({k: str(v) for k, v in valores.items()})
        return {k: str(v) for k, v in valores.items()}

    def anexar(self, tabela: str, sys_id: str, arquivo: Path) -> str:
        self._simular("anexar (simulado)")
        self.anexados.append((tabela, sys_id, arquivo.name))
        return f"simulado-{len(self.anexados)}"

    def excluir_anexo(self, anexo_sys_id: str) -> None:
        self._simular("excluir_anexo (simulado)")

    def criar(self, tabela: str, valores: dict[str, Any]) -> dict[str, str]:
        raise RuntimeError("simulação: criar registro não é permitido")

    def excluir(self, tabela: str, sys_id: str) -> None:
        raise RuntimeError("simulação: excluir registro não é permitido")


def enviar_simulado(app: Any, pasta: Path) -> ResultadoTransmissao:
    pasta.mkdir(parents=True, exist_ok=True)
    comprovante = pasta / "comprovante_SIMULADO.pdf"
    comprovante.write_bytes(b"%PDF comprovante simulado - nada foi enviado")
    return ResultadoTransmissao("SIMULADO: nada foi enviado ao órgão", pasta, comprovante)


def ativar(runner: type) -> tuple[ServiceNowSomenteLeitura, Path]:
    """Liga a simulação neste processo e devolve o cliente somente leitura e a pasta da simulação.

    `runner` é a classe Runner em uso: com `python -m simba.runner` ela vive em __main__, não em simba.runner.
    """
    pasta = config.SIMBA_HOME / "Simulacao" / f"{datetime.now():%Y%m%d-%H%M%S}"
    pasta.mkdir(parents=True)
    config.TRANSMITIDOS = pasta / "Transmitidos"
    config.ARQUIVO_DIR = pasta / "Arquivo"
    config.TRABALHO_DIR = pasta / "Trabalho"
    config.TRANSMITIR_APOS_VALIDAR = True
    # Nunca há clique em Enviar.
    transmissao.enviar = enviar_simulado
    # Chave real quando o órgão tem uma completa no CSV de chaves; sem ela, a seleção da chave é pulada.
    acao_manual = sys.modules[runner.__module__].AcaoManual
    chave_do_orgao, carregar_chave = runner._chave_do_orgao, transmissao.carregar_chave

    def chave_do_orgao_ou_simulada(self: Any, atendimento: str) -> tuple[Path, str]:
        try:
            return chave_do_orgao(self, atendimento)
        except acao_manual as err:
            log.info("SIMULAÇÃO: %s; a seleção da chave será pulada", err)
            return pasta / CHAVE_SIMULADA, "senha-simulada"

    def carregar_chave_ou_pular(app: Any, chave: Path, senha: str) -> None:
        if chave.name != CHAVE_SIMULADA:
            carregar_chave(app, chave, senha)

    runner._chave_do_orgao = chave_do_orgao_ou_simulada
    transmissao.carregar_chave = carregar_chave_ou_pular
    return ServiceNowSomenteLeitura(config.SN_INSTANCIA, config.SN_USUARIO, config.SN_SENHA), pasta
