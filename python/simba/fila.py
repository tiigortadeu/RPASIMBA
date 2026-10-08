"""Work items das filas do RPA Hub (sn_rpa_fdn_work_queue_item).

O usuário de integração é bloqueado acima de 100 requisições/minuto, então cada gravação conta. Pensado para um
runner por fila: a reserva lê o item e grava status=in_progress com um token próprio em `remarks`, sem releitura.
A única conferência de posse (`confirmar`) é feita ao entrar numa etapa sem retorno (ex.: "enviando"), logo antes
do Enviar: se outro runner tiver assumido o item, este desiste antes de transmitir.
As demais etapas ficam só no item local (log e comentário de falha). O heartbeat mantém o lease (sys_updated_on);
o reaper devolve itens de runners que caíram.
"""
import logging
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterator, Optional

from simba import config
from simba.servicenow import ServiceNow, ServiceNowError, agora_utc, formatar_data, ler_data

log = logging.getLogger(__name__)

TABELA = "sn_rpa_fdn_work_queue_item"
CAMPOS = "sys_id,name,status,locked,remarks,stage,attempts_count,deferred_till,request_content,sys_updated_on"
# Tamanho do campo response_content no SN.
MAX_RESPOSTA = 4000
# Itens pendentes trazidos por listagem (uma requisição serve para vários itens).
TAMANHO_LISTA = 50


# Só quem tem este papel explicitamente grava status/locked/stage/etc. do work item (ACL sn_rpa_fdn_work_queue_item.*).
PAPEL_ROBO = "sn_rpa_fdn.rpa_robot"
# Campos conferidos depois de cada gravação: o SN ignora em silêncio os que a ACL não permite.
CAMPOS_CONFERIDOS = ("status", "locked", "stage", "exception_type")


class ReservaPerdida(Exception):
    """Outro runner (ou o reaper) assumiu o item: não mexer mais nele."""


class SemPermissao(ServiceNowError):
    """O SN aceitou a gravação mas ignorou campos do work item por falta de permissão. Exige ação no SN."""


@dataclass
class Item:
    sys_id: str
    nome: str
    request: str
    tentativa: int
    marca: str
    etapa: str = "reservado"
    # sys_id da JUDTASK, preenchido pelo handler assim que lê o JSON (para comentar em caso de erro).
    judtask: Optional[str] = None


@dataclass
class Recolhido:
    """Item abandonado por um runner que caiu, devolvido ou falhado pelo reaper."""

    nome: str
    request: str
    etapa: str
    tentativa: int
    status: str  # "pending" ou "failure"
    motivo: str


class Fila:
    def __init__(
        self,
        sn: ServiceNow,
        nome: str,
        sem_retorno: frozenset[str] = frozenset(),
        runner_id: str = config.RUNNER_ID,
    ) -> None:
        self.sn = sn
        self.nome = nome
        # Etapas a partir das quais o item nunca volta para a fila (ex.: "enviando" no Transmissor).
        self.sem_retorno = sem_retorno
        self.runner_id = runner_id
        # O heartbeat roda em outra thread e a requests.Session não é thread-safe.
        self._lock = threading.Lock()
        self._candidatos: list[str] = []
        # Lista escolhida no console: só esses itens, sem consultar a fila; falhas podem ser reprocessadas.
        self._lista_fixa = False

    def usar_lista(self, sys_ids: list[str]) -> None:
        self._candidatos = list(sys_ids)
        self._lista_fixa = True

    def _ler(self, sys_id: str) -> dict[str, str]:
        with self._lock:
            return self.sn.obter(TABELA, sys_id, CAMPOS)

    def _gravar(self, sys_id: str, valores: dict[str, object]) -> None:
        with self._lock:
            gravado = self.sn.atualizar(TABELA, sys_id, valores, campos=",".join(valores))
        # O SN responde 200 mas ignora campos sem permissão de escrita (ACL de campo): confere na resposta.
        ignorados = [c for c in CAMPOS_CONFERIDOS if c in valores and gravado.get(c) != str(valores[c])]
        if ignorados:
            raise SemPermissao(
                f"O ServiceNow não gravou {', '.join(ignorados)} no work item {sys_id}: o usuário de integração "
                f"precisa do papel {PAPEL_ROBO} (ACL {TABELA}.*)"
            )

    # --- reserva -----------------------------------------------------------

    def reservar(self) -> Optional[Item]:
        """Reserva o próximo item pendente da fila; None se não houver.

        Uma listagem serve para vários itens: só consulta a fila de novo quando os candidatos acabam.
        """
        for _ in range(2):
            if not self._candidatos and self._lista_fixa:
                return None
            if not self._candidatos:
                agora = agora_utc()
                with self._lock:
                    pendentes = self.sn.listar(
                        TABELA,
                        f"work_queue.name={self.nome}{filtro_desde()}^status=pending^locked=false^ORDERBYsys_created_on",
                        "sys_id,deferred_till",
                        TAMANHO_LISTA,
                    )
                self._candidatos = [p["sys_id"] for p in pendentes if (ler_data(p["deferred_till"]) or agora) <= agora]
                if not self._candidatos:
                    return None
            while self._candidatos:
                item = self._tentar_reservar(self._candidatos.pop(0))
                if item:
                    return item
        return None

    def _tentar_reservar(self, sys_id: str) -> Optional[Item]:
        # A lista pode ter alguns minutos: relê o item antes de gravar por cima.
        atual = self._ler(sys_id)
        reservaveis = ("pending", "failure") if self._lista_fixa else ("pending",)
        if atual["status"] not in reservaveis or atual["locked"] == "true":
            log.info("Item %s não reservado: status %s, locked %s", atual["name"], atual["status"], atual["locked"])
            return None
        marca = f"runner={self.runner_id};token={uuid.uuid4().hex}"
        tentativa = int(atual["attempts_count"] or 0) + 1
        try:
            self._gravar(
                sys_id,
                {
                    "status": "in_progress",
                    "locked": "true",
                    "remarks": marca,
                    "stage": "reservado",
                    "last_started_time": formatar_data(agora_utc()),
                    "attempts_count": tentativa,
                },
            )
        except SemPermissao:
            # O remarks tem ACL própria e pode ter sido gravado: devolve o valor anterior.
            with self._lock:
                self.sn.atualizar(TABELA, sys_id, {"remarks": atual["remarks"]})
            raise
        log.info("Reservado %s (tentativa %d)", atual["name"], tentativa)
        return Item(sys_id, atual["name"], atual["request_content"], tentativa, marca)

    def confirmar(self, item: Item) -> None:
        if self._ler(item.sys_id)["remarks"] != item.marca:
            raise ReservaPerdida(f"{item.nome} não está mais reservado para este runner")

    # --- andamento -----------------------------------------------------------

    def etapa(self, item: Item, etapa: str) -> None:
        """Registra a etapa atual. Só vai ao SN a entrada numa etapa sem retorno, depois de conferir a posse.

        Ex.: "enviando" é gravado (e conferido) antes do Enviar, para o reaper nunca devolver um item que pode ter
        sido transmitido. As outras etapas ficam no item local (log e comentário de falha) e não gastam requisição.
        """
        if etapa in self.sem_retorno and item.etapa not in self.sem_retorno:
            self.confirmar(item)
            self._gravar(item.sys_id, {"stage": etapa})
        # Só depois de gravada: se o SN falhar antes, a etapa (ex.: "enviando") não começou.
        item.etapa = etapa

    def iniciar_heartbeat(self, item: Item) -> Callable[[], None]:
        """Renova o lease do item a cada HEARTBEAT segundos até a função devolvida ser chamada."""
        parar = threading.Event()

        def bater() -> None:
            while not parar.wait(config.HEARTBEAT):
                try:
                    self._gravar(item.sys_id, {"stage": item.etapa})
                except Exception:
                    # Sem heartbeat o reaper devolve o item; a conferência antes do Enviar percebe a perda.
                    log.exception("Heartbeat de %s falhou", item.nome)

        thread = threading.Thread(target=bater, name=f"heartbeat-{item.nome}", daemon=True)
        thread.start()

        def encerrar() -> None:
            parar.set()
            thread.join()

        return encerrar

    @contextmanager
    def heartbeat(self, item: Item) -> Iterator[None]:
        encerrar = self.iniciar_heartbeat(item)
        try:
            yield
        finally:
            encerrar()

    # --- conclusão -------------------------------------------------------------

    def concluir(self, item: Item, resposta: str) -> None:
        self._gravar(
            item.sys_id,
            {"status": "success", "locked": "false", "stage": "concluido", "response_content": resposta[:MAX_RESPOSTA]},
        )
        log.info("%s concluído: %s", item.nome, resposta)

    def falhar(self, item: Item, tipo: str, mensagem: str) -> None:
        """Falha definitiva: `business` (dados/arquivos recusados) ou `application` (exige ação manual)."""
        self._gravar(
            item.sys_id,
            {
                "status": "failure",
                "exception_type": tipo,
                "locked": "false",
                "response_content": mensagem[:MAX_RESPOSTA],
            },
        )
        log.warning("%s falhou (%s): %s", item.nome, tipo, mensagem)

    def devolver(self, item: Item, mensagem: str) -> str:
        """Falha técnica: volta para a fila com espera crescente, até MAX_TENTATIVAS.

        Devolve o status final: "pending" (nova tentativa) ou "failure" (sem retorno ou tentativas esgotadas).
        """
        if item.etapa in self.sem_retorno:
            self.falhar(item, "application", f"Falha na etapa {item.etapa}; verificar manualmente: {mensagem}")
            return "failure"
        if item.tentativa >= config.MAX_TENTATIVAS:
            self.falhar(item, "application", f"Falhou {item.tentativa} vezes: {mensagem}")
            return "failure"
        espera = timedelta(minutes=5 * item.tentativa)
        self._gravar(item.sys_id, _pendente(mensagem, agora_utc() + espera))
        log.warning("%s devolvido à fila (tentativa %d): %s", item.nome, item.tentativa, mensagem)
        return "pending"

    # --- runners que caíram ------------------------------------------------------

    def reaper(self) -> list[Recolhido]:
        """Devolve (ou falha) itens em andamento cujo runner parou de dar heartbeat."""
        with self._lock:
            andamento = self.sn.listar(
                TABELA, f"work_queue.name={self.nome}{filtro_desde()}^status=in_progress", CAMPOS, 200
            )
        limite = agora_utc() - timedelta(seconds=config.LEASE)
        recolhidos = []
        for item in andamento:
            if ler_data(item["sys_updated_on"]) >= limite:
                continue
            atual = self._ler(item["sys_id"])
            # Relido: o dono pode ter dado heartbeat entre a listagem e agora.
            if atual["status"] != "in_progress" or ler_data(atual["sys_updated_on"]) >= limite:
                continue
            motivo = f"Runner parou de responder na etapa {atual['stage']!r} ({atual['remarks']})"
            if atual["stage"] in self.sem_retorno:
                valores = _falha("application", f"{motivo}; verificar manualmente")
            elif int(atual["attempts_count"] or 0) >= config.MAX_TENTATIVAS:
                valores = _falha("application", motivo)
            else:
                valores = _pendente(motivo, agora_utc())
            self._gravar(atual["sys_id"], valores)
            log.warning("Reaper: %s -> %s (%s)", atual["name"], valores["status"], motivo)
            recolhidos.append(
                Recolhido(
                    atual["name"],
                    atual["request_content"],
                    atual["stage"],
                    int(atual["attempts_count"] or 0),
                    str(valores["status"]),
                    motivo,
                )
            )
        return recolhidos


def filtro_desde() -> str:
    """Trecho de query que restringe aos work items criados a partir de ITENS_DESDE (fuso do usuário do SN)."""
    if not config.ITENS_DESDE:
        return ""
    return f"^sys_created_on>=javascript:gs.dateGenerate('{config.ITENS_DESDE}','00:00:00')"


def _pendente(mensagem: str, a_partir_de: datetime) -> dict[str, object]:
    return {
        "status": "pending",
        "locked": "false",
        "remarks": "",
        "stage": "",
        "deferred_till": formatar_data(a_partir_de),
        "response_content": mensagem[:MAX_RESPOSTA],
    }


def _falha(tipo: str, mensagem: str) -> dict[str, object]:
    return {"status": "failure", "exception_type": tipo, "locked": "false", "response_content": mensagem[:MAX_RESPOSTA]}
