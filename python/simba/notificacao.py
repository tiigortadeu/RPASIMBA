"""Registra na JUDTASK por que um work item parou: em que ponto, qual erro e o que o usuário deve fazer.

Falha definitiva vai para "Comentários adicionais" (visível ao usuário, que trata manualmente). Falha técnica com
nova tentativa automática vai para as notas de trabalho, para não poluir os comentários a cada tentativa.
"""
import json
from dataclasses import dataclass
from typing import Optional

from simba.servicenow import TABELA_TAREFAS, ServiceNow

ETAPAS = {
    "reservado": "início do processamento",
    "baixando": "download dos arquivos anexados à tarefa",
    "validando": "cadastro e validação no Simba Validador",
    "anexando": "envio dos arquivos gerados para a tarefa",
    "preparando_envio": "preparação da transmissão (arquivo de chaves e senha)",
    "enviando": "transmissão pelo Simba Transmissor",
    "registrando": "registro do comprovante na tarefa",
}

NEGOCIO = "negocio"
MANUAL = "manual"
NOVA_TENTATIVA = "nova_tentativa"
ORIENTACOES = {
    NEGOCIO: "Corrija os dados ou os arquivos da tarefa e reenvie para o RPA. O RPA não tentará de novo sozinho.",
    MANUAL: "Verifique e trate manualmente. O RPA não tentará de novo sozinho.",
    NOVA_TENTATIVA: "O RPA tentará de novo automaticamente; nenhuma ação é necessária por enquanto.",
}
TITULOS = {
    NEGOCIO: "Erro de validação/dados",
    MANUAL: "Falha que exige tratamento manual",
    NOVA_TENTATIVA: "Falha técnica (nova tentativa automática)",
}


@dataclass
class Parada:
    processo: str  # nome da fila, ex.: "Simba Validador"
    work_item: str
    etapa: str
    tentativa: int
    orientacao: str  # NEGOCIO, MANUAL ou NOVA_TENTATIVA
    erro: str
    runner: str
    detalhe: str = ""  # ex.: último passo executado no Simba


def montar_comentario(parada: Parada) -> str:
    linhas = [
        f"[RPA {parada.processo}] {TITULOS[parada.orientacao]}",
        f"Parou em: {ETAPAS.get(parada.etapa, parada.etapa or 'desconhecido')}",
        f"Erro: {parada.erro}",
    ]
    if parada.detalhe:
        linhas.append(f"Detalhe: {parada.detalhe}")
    linhas += [
        f"O que fazer: {ORIENTACOES[parada.orientacao]}",
        f"Work item: {parada.work_item} | tentativa {parada.tentativa} | runner {parada.runner}",
    ]
    return "\n".join(linhas)


def resolver_judtask(sn: ServiceNow, nome_item: str, request: str) -> Optional[str]:
    """sys_id da JUDTASK: campo Judtask do JSON ou, se o JSON for inválido, o número no nome do work item."""
    try:
        dados = json.loads(request)
    except ValueError:
        # JSON inválido é justamente um dos erros a reportar; segue pelo nome do item.
        dados = None
    if isinstance(dados, dict) and dados.get("Judtask"):
        return dados["Judtask"]
    numero = nome_item.rsplit("_", 1)[-1]
    if not numero.startswith("JUDTASK"):
        return None
    tarefas = sn.listar(TABELA_TAREFAS, f"number={numero}", "sys_id", 1)
    return tarefas[0]["sys_id"] if tarefas else None


def montar_nota_correcoes(processo: str, work_item: str, correcoes: list[str]) -> str:
    linhas = [f"[RPA {processo}] Correções automáticas aplicadas aos arquivos antes da validação aprovada:"]
    linhas += [f"- {c}" for c in correcoes]
    linhas.append(f"Os anexos originais da tarefa não foram alterados. Work item: {work_item}")
    return "\n".join(linhas)


def registrar_correcoes(sn: ServiceNow, judtask: str, processo: str, work_item: str, correcoes: list[str]) -> None:
    """Nota de trabalho (auditoria) com o que foi alterado nos arquivos validados."""
    sn.atualizar(TABELA_TAREFAS, judtask, {"work_notes": montar_nota_correcoes(processo, work_item, correcoes)})


def comentar(sn: ServiceNow, judtask: str, parada: Parada) -> None:
    campo = "work_notes" if parada.orientacao == NOVA_TENTATIVA else "comments"
    sn.atualizar(TABELA_TAREFAS, judtask, {campo: montar_comentario(parada)})
