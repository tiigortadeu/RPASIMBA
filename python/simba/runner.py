"""Processa itens das filas Simba Validador e Simba Transmissor do RPA Hub.

Cada runner é uma sessão Windows com o Simba instalado; vários runners rodam em paralelo sem estado próprio:
tudo vem do ServiceNow (JSON, anexos) e volta para ele (anexos, status do work item).

O entrypoint oficial é ``bot.py``. Esta implementação expõe a operação unitária usada
por ele; o loop contínuo abaixo permanece apenas como código legado durante a migração.
"""
import argparse
import json
import logging
import logging.handlers
import os
import shutil
import stat
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from simba import arquivo, chaves, config, fluxo, notificacao, simulacao
from simba.andamento import Andamento
from simba.app import TRANSMISSOR, VALIDADOR, SimbaApp, SimbaAviso, StepFailed
from simba.cadastro import Caso
from simba.fila import Fila, Item, ReservaPerdida, SemPermissao
from simba.geracao import ResultadoGeracao
from simba.servicenow import TABELA_TAREFAS, ServiceNow, ServiceNowError
from simba.transmissao import ResultadoTransmissao, TransmissaoIncerta

log = logging.getLogger("simba.runner")

FILAS = {"validador": "Simba Validador", "transmissor": "Simba Transmissor"}
# Anexos de campo do tipo file_attachment ficam numa tabela "ZZ_YY<tabela>".
TABELA_EVIDENCIA = f"ZZ_YY{TABELA_TAREFAS}"


class DadosInvalidos(Exception):
    """Work item ou tarefa com dados que impedem o processamento. Repetir não resolve."""


class AcaoManual(Exception):
    """Repetir não resolve e não é erro dos dados: falta chave/senha no runner, comprovante não encontrado etc."""


@dataclass
class CasoBaixado:
    caso: Caso
    judtask: str
    # Anexos atuais da JUDTASK, para substituir os de mesmo nome ao subir a saída.
    anexos: list[dict[str, str]]


@dataclass
class CasoGerado:
    resultado: ResultadoGeracao
    transmitido: Optional[ResultadoTransmissao]


@dataclass
class EmAndamento:
    """Item reservado na esteira, com o heartbeat ligado até ser concluído ou parado."""

    item: Item
    pasta: Path
    encerrar_heartbeat: Callable[[], None]
    inicio: float
    baixado: Optional[CasoBaixado] = field(default=None)


class Runner:
    def __init__(self, sn: ServiceNow, filas: list[str]) -> None:
        self.sn = sn
        # Depois do Enviar o item nunca volta para a fila (vale também para o Validador quando ele já transmite).
        self.filas = {nome: Fila(sn, FILAS[nome], frozenset({"enviando", "registrando"})) for nome in filas}
        self.handlers: dict[str, Callable[[Fila, Item, Path], None]] = {
            "validador": self.validador,
            "transmissor": self.transmissor,
        }
        self.app_validador = SimbaApp(VALIDADOR)
        self.app_transmissor = SimbaApp(TRANSMISSOR)
        self._ultimo_reaper = 0.0
        # Quantos passos do Simba já existiam ao começar o item atual (para citar o passo em que parou).
        self._timings_no_inicio = (0, 0)
        # Pastas de trabalho em uso pelo Validador aberto, apagadas quando ele for fechado (esteira).
        self._limpar_ao_fechar: list[Path] = []
        # Andamento do lote para o console (só quando o lote vem do console ou da linha de comando).
        self.andamento: Optional[Andamento] = None

    # --- loop ------------------------------------------------------------------

    def executar(self, uma_vez: bool = False) -> None:
        try:
            while True:
                self._reaper()
                processou = False
                # Um item de cada fila por volta: uma fila cheia não trava a outra.
                for nome in self.filas:
                    try:
                        if self.processar_proximo(nome):
                            processou = True
                            if uma_vez:
                                return
                    except Exception:
                        # Ex.: SN fora do ar ao reservar, disco cheio. O runner continua; se um item ficou em
                        # andamento, o reaper o recolhe depois do lease e comenta na JUDTASK.
                        log.exception("Falha fora do processamento de item na fila %s", FILAS[nome])
                        if uma_vez:
                            raise
                        time.sleep(config.FILA_VAZIA_ESPERA)
                if not processou:
                    if uma_vez:
                        return
                    time.sleep(config.FILA_VAZIA_ESPERA)
        finally:
            self.app_validador.kill()
            self.app_transmissor.kill()

    def _reaper(self) -> None:
        if time.monotonic() - self._ultimo_reaper < config.REAPER_INTERVALO:
            return
        self._ultimo_reaper = time.monotonic()
        for fila in self.filas.values():
            try:
                recolhidos = fila.reaper()
            except ServiceNowError:
                log.exception("Reaper da fila %s falhou", fila.nome)
                continue
            for r in recolhidos:
                orientacao = notificacao.NOVA_TENTATIVA if r.status == "pending" else notificacao.MANUAL
                self._comentar(
                    notificacao.Parada(fila.nome, r.nome, r.etapa, r.tentativa, orientacao, r.motivo, config.RUNNER_ID),
                    None,
                    r.request,
                )

    def processar_proximo(self, nome: str) -> bool:
        fila = self.filas[nome]
        item = fila.reservar()
        if item is None:
            return False
        pasta = config.TRABALHO_DIR / item.sys_id
        _limpar(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        inicio = time.monotonic()
        self._timings_no_inicio = (len(self.app_validador.timings), len(self.app_transmissor.timings))
        try:
            with fila.heartbeat(item):
                self._executar_item(self.handlers[nome], fila, item, pasta)
        finally:
            log.info("%s: %.1fs", item.nome, time.monotonic() - inicio)
            _limpar(pasta)
        return True

    def processar_um_item(self) -> dict[str, object]:
        """Processa no máximo um item entre as filas configuradas e retorna um resumo JSON."""
        self._reaper()
        for nome in self.filas:
            try:
                if self.processar_proximo(nome):
                    return {"status": "processed", "queue": nome}
            except Exception:
                log.exception("Falha fora do processamento de item na fila %s", FILAS[nome])
                raise
        return {"status": "empty", "queue": None}

    def _executar_item(self, handler: Callable[[Fila, Item, Path], None], fila: Fila, item: Item, pasta: Path) -> None:
        """Roda o handler; qualquer parada vira status no work item + comentário na JUDTASK."""
        try:
            handler(fila, item, pasta)
        except Exception as err:
            self._registrar_parada(fila, item, err, self._passo_simba())

    def _registrar_parada(self, fila: Fila, item: Item, err: Exception, detalhe: str = "") -> None:
        """Grava a falha no work item (devolve à fila ou falha de vez) e comenta na JUDTASK."""
        if isinstance(err, ReservaPerdida):
            # Outro runner (ou o reaper) assumiu o item; quem assumiu registra o que acontecer.
            log.warning("%s", err)
            self._anotar(item, "Assumido por outro runner", str(err))
            return
        if isinstance(err, SimbaAviso) and item.etapa == "preparando_envio":
            # Recusa do Transmissor ao carregar a chave (arquivo inválido, senha errada): configuração do runner.
            erro, tipo, orientacao = err.message, "application", notificacao.MANUAL
        elif isinstance(err, (SimbaAviso, DadosInvalidos)):
            erro, tipo, orientacao = getattr(err, "message", str(err)), "business", notificacao.NEGOCIO
        elif isinstance(err, (TransmissaoIncerta, AcaoManual)):
            erro, tipo, orientacao = str(err), "application", notificacao.MANUAL
        elif isinstance(err, (StepFailed, ServiceNowError, OSError)):
            erro, tipo, orientacao = str(err), None, None
        else:
            # Erro inesperado: registra e devolve (conta tentativa) em vez de derrubar o runner.
            log.error("Erro inesperado em %s", item.nome, exc_info=err)
            erro, tipo, orientacao = f"{type(err).__name__}: {err}", None, None

        # A etapa no início da mensagem do work item diz ao console se o caso chegou a ser validado.
        registro = f"[{item.etapa}] {erro}"
        try:
            if tipo is None:
                status = fila.devolver(item, registro)
                orientacao = notificacao.NOVA_TENTATIVA if status == "pending" else notificacao.MANUAL
            else:
                fila.falhar(item, tipo, registro)
        except (ServiceNowError, ReservaPerdida):
            # Sem conseguir atualizar o work item, o reaper o recolhe depois do lease (e comenta).
            log.exception("Não foi possível registrar a falha de %s no work item", item.nome)
            self._anotar(item, "Falha (não registrada no ServiceNow)", erro, "Técnico")
            return
        if orientacao == notificacao.NOVA_TENTATIVA:
            self._anotar(item, "Pendente (nova tentativa)", erro, "Técnico (nova tentativa)")
        else:
            self._anotar(item, "Falha", erro, "Dados/arquivos" if orientacao == notificacao.NEGOCIO else "Ação manual")
        parada = notificacao.Parada(
            fila.nome, item.nome, item.etapa, item.tentativa, orientacao, erro, config.RUNNER_ID, detalhe
        )
        self._comentar(parada, item.judtask, item.request)

    def _anotar(self, item: Item, situacao: str, mensagem: str = "", categoria: str = "") -> None:
        if self.andamento:
            self.andamento.finalizado(item.nome.rsplit("_", 1)[-1], situacao, mensagem, categoria)

    def _passo_simba(self) -> str:
        """Último passo do Simba executado neste item, ex.: 'validar_e_gerar (falhou após 3 tentativas)'."""
        # Cada item usa só um dos dois programas.
        novos = self.app_validador.timings[self._timings_no_inicio[0] :]
        novos += self.app_transmissor.timings[self._timings_no_inicio[1] :]
        if not novos:
            return ""
        ultimo = novos[-1]
        situacao = "concluído" if ultimo.ok else f"falhou após {ultimo.attempts} tentativa(s)"
        return f"último passo no Simba: {ultimo.step} ({situacao})"

    def _comentar(self, parada: notificacao.Parada, judtask: Optional[str], request: str) -> None:
        """Comenta na JUDTASK; uma falha aqui só é registrada em log (o status do work item já foi gravado)."""
        try:
            judtask = judtask or notificacao.resolver_judtask(self.sn, parada.work_item, request)
            if judtask is None:
                log.error("Sem JUDTASK para comentar a parada de %s: %s", parada.work_item, parada.erro)
                return
            notificacao.comentar(self.sn, judtask, parada)
        except ServiceNowError:
            log.exception("Não foi possível comentar na JUDTASK de %s", parada.work_item)

    # --- Simba Validador ---------------------------------------------------------

    def _dados_validador(self, item: Item) -> dict:
        if item.request.strip():
            return json.loads(item.request)
        # Sem request_content: o JSON do caso fica na description da tarefa (SimbaValidador_<número>).
        numero = item.nome.rsplit("_", 1)[-1]
        tarefas = self.sn.listar(TABELA_TAREFAS, f"number={numero}", "description", 1)
        if not tarefas:
            raise DadosInvalidos(f"Tarefa {numero} não encontrada")
        return json.loads(tarefas[0]["description"])

    def validador(self, fila: Fila, item: Item, pasta: Path) -> None:
        """Um item do início ao fim (loop legado e processar_um_item): fecha o Simba e arquiva ao terminar."""
        baixado = self._baixar_caso(fila, item, pasta)
        if baixado is None:
            return
        try:
            gerado = self._processar_no_simba(fila, item, pasta, baixado)
        finally:
            # Sucesso ou falha: o atendimento sai das listas do Simba (os programas precisam estar fechados).
            self.app_validador.kill()
            self.app_transmissor.kill()
            _arquivar(baixado.caso.pasta)
        self._registrar_resultado(fila, item, pasta, baixado, gerado)

    def _baixar_caso(self, fila: Fila, item: Item, pasta: Path) -> Optional["CasoBaixado"]:
        """Lê o caso e baixa os GABs para pasta/<atendimento>; None se já foi transmitido (o item é concluído)."""
        try:
            dados = self._dados_validador(item)
            item.judtask = dados.get("Judtask")
            caso = Caso.from_json(dados)
            judtask = dados["Judtask"]
        except (ValueError, KeyError, AttributeError) as err:
            raise DadosInvalidos(f"JSON do caso inválido ou incompleto: {err!r}") from err
        fila.etapa(item, "baixando")
        # Uma requisição traz os anexos da tarefa e o comprovante (campo evidence_attachment, anexo em ZZ_YY<tabela>).
        anexos = self.sn.anexos(TABELA_TAREFAS, judtask, TABELA_EVIDENCIA)
        if config.TRANSMITIR_APOS_VALIDAR and any(a["table_name"] == TABELA_EVIDENCIA for a in anexos):
            # Anti-duplicidade: o comprovante só é gravado depois de um envio bem-sucedido.
            fila.concluir(item, f"Comprovante já registrado na tarefa; atendimento {caso.pasta} não reenviado")
            self._anotar(item, "Sucesso", "Comprovante já registrado; não reenviado")
            return None
        da_tarefa = [a for a in anexos if a["table_name"] == TABELA_TAREFAS]
        # Só os arquivos de entrada: a tarefa também guarda a saída de execuções anteriores.
        # A tarefa costuma ter cada GAB anexado em dobro (mesmo nome e conteúdo): um download por nome.
        entradas = list({a["file_name"]: a for a in da_tarefa if _arquivo_de_entrada(a["file_name"], caso.pasta)}.values())
        if not entradas:
            raise DadosInvalidos(f"Tarefa {judtask} sem arquivos {caso.pasta}_*.txt para validar")
        arquivos = pasta / caso.pasta
        arquivos.mkdir()
        for anexo in entradas:
            self.sn.baixar_anexo(anexo, arquivos)
        return CasoBaixado(caso, judtask, da_tarefa)

    def _processar_no_simba(self, fila: Fila, item: Item, pasta: Path, baixado: "CasoBaixado") -> "CasoGerado":
        """Validador (cadastro, validação, pacote) e, com TRANSMITIR_APOS_VALIDAR, o envio pelo Transmissor."""
        caso = baixado.caso
        arquivos = pasta / caso.pasta
        fila.etapa(item, "validando")
        resultado = fluxo.processar(self.app_validador, caso, arquivos)
        # Copiada já para a pasta de trabalho: o dadosValidador só é arquivado quando o Validador fechar.
        _copiar_saida(arquivo.dados_validador(caso.pasta), arquivos, pasta / "saida", caso.pasta)
        if not config.TRANSMITIR_APOS_VALIDAR:
            return CasoGerado(resultado, None)
        # Transmite já com o pacote gerado nesta máquina, sem esperar a tarefa/fila do Transmissor.
        fila.etapa(item, "preparando_envio")
        chave, senha = self._chave_do_orgao(caso.pasta)
        # O Transmissor só lê a lista de atendimentos ao abrir.
        self.app_transmissor.kill()
        arquivo.sincronizar_transmissor(caso.pasta)
        transmitido = fluxo.transmitir(
            self.app_transmissor,
            caso.pasta,
            arquivos,
            chave,
            senha,
            antes_de_enviar=lambda: fila.etapa(item, "enviando"),
        )
        return CasoGerado(resultado, transmitido)

    def _registrar_resultado(
        self, fila: Fila, item: Item, pasta: Path, baixado: "CasoBaixado", gerado: "CasoGerado"
    ) -> None:
        """Comprovante, saída do Validador e auditoria na JUDTASK; por fim conclui o work item."""
        caso, judtask, resultado = baixado.caso, baixado.judtask, gerado.resultado
        resposta = f"{caso.pasta} validado e gerado; hash {resultado.hash}"
        if gerado.transmitido:
            fila.etapa(item, "registrando")
            # Primeiro o comprovante: é ele que impede um reenvio.
            self._registrar_comprovante(judtask, gerado.transmitido)
            resposta += f"; transmitido: {gerado.transmitido.mensagem}"
        else:
            fila.etapa(item, "anexando")
        self._anexar_saida(judtask, pasta / "saida", baixado.anexos)
        if resultado.correcoes:
            # Auditoria: o que mudou nos arquivos validados.
            notificacao.registrar_correcoes(self.sn, judtask, fila.nome, item.nome, resultado.correcoes)
            resposta += f"; {len(resultado.correcoes)} correção(ões) automática(s) nos arquivos"
        fila.concluir(item, resposta)
        self._anotar(item, "Sucesso", resposta)

    def _anexar_saida(self, judtask: str, saida: Path, anexados: list[dict[str, str]]) -> None:
        """Sobe a saída do Validador; substitui anexos de mesmo nome (num reprocessamento a saída é regerada)."""
        for gerado in sorted(saida.iterdir()):
            for antigo in anexados:
                if antigo["file_name"] == gerado.name:
                    self.sn.excluir_anexo(antigo["sys_id"])
            self.sn.anexar(TABELA_TAREFAS, judtask, gerado)

    # --- Simba Validador em esteira ------------------------------------------------

    def processar_lote(self, max_itens: int, sys_ids: Optional[list[str]] = None) -> dict[str, object]:
        """Até `max_itens` itens da fila do Validador, com o SN em paralelo ao Simba.

        O limite de requisições do SN, e não o Simba, é o gargalo: enquanto o Simba processa um caso, uma thread
        baixa o próximo e registra o anterior. O Validador fica aberto entre os casos; a cada VALIDADOR_REINICIO
        casos ele é reiniciado e os casos acumulados saem do dadosValidador (só dá para arquivar com ele fechado).
        Com `sys_ids` (seleção do console), processa só esses work items. Com andamento, o console pode pedir a
        parada: o caso em andamento termina e nenhum outro é reservado.
        """
        fila = self.filas["validador"]
        if sys_ids is not None:
            fila.usar_lista(sys_ids)
        self._reaper()
        processados = 0
        no_simba: list[str] = []
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="servicenow") as sn:
                proximo = sn.submit(self._reservar_e_baixar, fila)
                while processados < max_itens:
                    atual = proximo.result()
                    if atual is None:
                        break
                    processados += 1
                    parar = self.andamento is not None and self.andamento.parada_pedida()
                    if processados < max_itens and not parar:
                        proximo = sn.submit(self._reservar_e_baixar, fila)
                    no_simba.append(atual.baixado.caso.pasta)
                    if self.andamento:
                        self.andamento.em_execucao(
                            atual.item.nome.rsplit("_", 1)[-1], atual.baixado.caso.pasta, "Simba (validação e envio)"
                        )
                    self._timings_no_inicio = (len(self.app_validador.timings), len(self.app_transmissor.timings))
                    try:
                        gerado = self._processar_no_simba(fila, atual.item, atual.pasta, atual.baixado)
                    except Exception as err:
                        sn.submit(self._parar_item, atual, err, self._passo_simba())
                    else:
                        sn.submit(self._concluir_item, atual, gerado)
                    if len(no_simba) >= config.VALIDADOR_REINICIO:
                        self._fechar_e_arquivar(no_simba)
                    if parar:
                        log.info("Parada pedida pelo console: lote encerrado depois de %d item(ns)", processados)
                        break
        finally:
            self._fechar_e_arquivar(no_simba)
        return {"status": "processed" if processados else "empty", "queue": "validador", "itens": processados}

    def _reservar_e_baixar(self, fila: Fila) -> Optional["EmAndamento"]:
        """Thread do SN: reserva o próximo item e baixa o caso; itens com erro ou já transmitidos são registrados
        e pulados. None quando a fila acaba."""
        while (item := self._reservar(fila)) is not None:
            pasta = config.TRABALHO_DIR / item.sys_id
            atual = EmAndamento(item, pasta, fila.iniciar_heartbeat(item), time.monotonic())
            try:
                _limpar(pasta)
                pasta.mkdir(parents=True, exist_ok=True)
                atual.baixado = self._baixar_caso(fila, item, pasta)
            except Exception as err:
                self._parar_item(atual, err)
                continue
            if atual.baixado is not None:
                return atual
            self._encerrar(atual)
        return None

    def _reservar(self, fila: Fila) -> Optional[Item]:
        """Reserva o próximo item; uma instabilidade do SN não derruba o lote: espera e tenta de novo."""
        for tentativa in range(1, config.RESERVA_TENTATIVAS + 1):
            try:
                return fila.reservar()
            except SemPermissao:
                # Falta de papel no usuário de integração: todo item falharia igual.
                raise
            except ServiceNowError:
                if tentativa == config.RESERVA_TENTATIVAS:
                    raise
                log.exception("Falha ao reservar na fila %s (tentativa %d); nova tentativa em %ds", fila.nome, tentativa, config.FILA_VAZIA_ESPERA)
                time.sleep(config.FILA_VAZIA_ESPERA)
        return None

    def _concluir_item(self, atual: "EmAndamento", gerado: "CasoGerado") -> None:
        try:
            self._registrar_resultado(self.filas["validador"], atual.item, atual.pasta, atual.baixado, gerado)
        except Exception as err:
            self._registrar_parada(self.filas["validador"], atual.item, err)
        finally:
            self._encerrar(atual)

    def _parar_item(self, atual: "EmAndamento", err: Exception, detalhe: str = "") -> None:
        try:
            self._registrar_parada(self.filas["validador"], atual.item, err, detalhe)
        finally:
            self._encerrar(atual)

    def _encerrar(self, atual: "EmAndamento") -> None:
        atual.encerrar_heartbeat()
        log.info("%s: %.1fs", atual.item.nome, time.monotonic() - atual.inicio)
        try:
            _apagar(atual.pasta)
        except OSError:
            # O Validador aberto mantém a pasta dos GABs em uso: apaga quando ele fechar.
            self._limpar_ao_fechar.append(atual.pasta)

    def _fechar_e_arquivar(self, atendimentos: list[str]) -> None:
        self.app_validador.kill()
        self.app_transmissor.kill()
        for atendimento in atendimentos:
            _arquivar(atendimento)
        atendimentos.clear()
        while self._limpar_ao_fechar:
            _limpar(self._limpar_ao_fechar.pop())

    def _chave_do_orgao(self, atendimento: str) -> tuple[Path, str]:
        """(arquivo .ASB, senha) do órgão de destino do atendimento, pelo CSV de chaves (ex.: 002-PF-... -> 002)."""
        try:
            return chaves.da_orgao(chaves.orgao_do_atendimento(atendimento))
        except chaves.ChaveIndisponivel as err:
            raise AcaoManual(str(err)) from err

    def _registrar_comprovante(self, judtask: str, resultado: ResultadoTransmissao) -> None:
        """Comprovante no campo evidence_attachment da tarefa (file_attachment: anexo em ZZ_YY<tabela>)."""
        if resultado.comprovante is None:
            raise AcaoManual(f"Enviado, mas o comprovante não foi encontrado: {resultado.mensagem}")
        anexo = self.sn.anexar(TABELA_EVIDENCIA, judtask, resultado.comprovante)
        self.sn.atualizar(TABELA_TAREFAS, judtask, {"evidence_attachment": anexo})

    # --- Simba Transmissor ---------------------------------------------------------

    def transmissor(self, fila: Fila, item: Item, pasta: Path) -> None:
        try:
            dados = json.loads(item.request)
            item.judtask = dados.get("Judtask")
            judtask, atendimento = dados["Judtask"], dados["Simba"]
        except (ValueError, KeyError, AttributeError) as err:
            raise DadosInvalidos(f"Work item do Transmissor inválido: {err!r}") from err

        tarefa = self.sn.obter(TABELA_TAREFAS, judtask, "number,evidence_attachment")
        if tarefa["evidence_attachment"]:
            # Anti-duplicidade: o comprovante só é gravado depois de um envio bem-sucedido.
            fila.concluir(item, f"Comprovante já registrado em {tarefa['number']}; atendimento não reenviado")
            return

        chave, senha = self._chave_do_orgao(atendimento)
        try:
            self._transmitir(fila, item, pasta, tarefa, atendimento, chave, senha)
        finally:
            # Sucesso ou falha: o atendimento sai da lista do Transmissor. Em falha depois do Enviar, a pasta
            # arquivada guarda o estado local do Transmissor para a verificação manual.
            self.app_transmissor.kill()
            _arquivar(atendimento)

    def _transmitir(
        self, fila: Fila, item: Item, pasta: Path, tarefa: dict, atendimento: str, chave: Path, senha: str
    ) -> None:
        judtask = item.judtask
        fila.etapa(item, "baixando")
        anexos = {a["file_name"]: a for a in self.sn.anexos(TABELA_TAREFAS, judtask)}
        pacote = [f"{atendimento}.zip", f"{atendimento}.zip.hash", f"{atendimento}-tipo-atendimento.txt"]
        faltando = [nome for nome in pacote if nome not in anexos]
        if faltando:
            raise DadosInvalidos(f"Pacote incompleto em {tarefa['number']}: faltam {', '.join(faltando)}")
        envio = arquivo.dados_transmissor(atendimento) / "envio"
        envio.mkdir(parents=True, exist_ok=True)
        for nome in pacote:
            self.sn.baixar_anexo(anexos[nome], envio)
        # Cópias dos arquivos validados (arqtxt do Validador), para o zip em Transmitidos.
        gabs = pasta / "arquivos"
        gabs.mkdir()
        for nome, anexo in anexos.items():
            if _arquivo_de_entrada(nome, atendimento):
                self.sn.baixar_anexo(anexo, gabs)
        if not any(gabs.iterdir()):
            log.warning("%s: nenhum arquivo validado anexado; o zip dos GABs não será gerado", tarefa["number"])

        # O Transmissor só lê a lista de atendimentos ao abrir.
        self.app_transmissor.kill()
        resultado = fluxo.transmitir(
            self.app_transmissor,
            atendimento,
            gabs if any(gabs.iterdir()) else None,
            chave,
            senha,
            antes_de_enviar=lambda: fila.etapa(item, "enviando"),
        )
        self.app_transmissor.kill()

        fila.etapa(item, "registrando")
        self._registrar_comprovante(judtask, resultado)
        fila.concluir(item, resultado.mensagem)


def _copiar_saida(dados: Path, originais: Path, saida: Path, atendimento: str) -> None:
    """Copia para `saida` o que vai anexado na JUDTASK a partir do dadosValidador do caso.

    Transmitindo aqui mesmo, tudo vai num zip só (cada anexo é uma requisição ao SN). Para a fila do Transmissor o
    pacote precisa ir solto (zip, hash, tipo de atendimento), como o Uploads do .iBot: pasta e subpastas de primeiro
    nível. Cópias dos arquivos de entrada (os GABs em arqtxt) só vão se diferirem (correção automática), com o
    sufixo _corrigido, e nunca apagam os originais da tarefa.
    """
    saida.mkdir()
    if config.TRANSMITIR_APOS_VALIDAR:
        with zipfile.ZipFile(saida / f"{atendimento}_saida_simba.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for gerado in sorted(dados.rglob("*")):
                if gerado.is_file():
                    z.write(gerado, gerado.relative_to(dados))
        return
    gerados = [p for p in dados.iterdir() if p.is_file()]
    gerados += [p for sub in dados.iterdir() if sub.is_dir() for p in sub.iterdir() if p.is_file()]
    for gerado in gerados:
        original = originais / gerado.name
        if not original.is_file():
            shutil.copy2(gerado, saida / gerado.name)
        elif gerado.read_bytes() != original.read_bytes():
            shutil.copy2(gerado, saida / f"{gerado.stem}_corrigido{gerado.suffix}")


# Gerados pelo Validador (arqtxt) com o mesmo prefixo dos arquivos de entrada.
GERADOS_PELO_SIMBA = ("_ATENDIMENTO.txt", "_INVESTIGADO.txt", "_corrigido.txt")


def _arquivo_de_entrada(nome: str, atendimento: str) -> bool:
    """GAB/CC 3454 enviado para validação: <atendimento>_<TIPO>.txt, fora os arquivos que o próprio RPA anexa."""
    return nome.startswith(f"{atendimento}_") and nome.endswith(".txt") and not nome.endswith(GERADOS_PELO_SIMBA)


def _arquivar(atendimento: str) -> None:
    """Arquiva sem lançar: depois de concluir o item, um erro aqui o devolveria à fila."""
    try:
        arquivo.arquivar_atendimento(atendimento)
    except OSError as err:
        log.warning("Não foi possível arquivar %s (continua na lista do Simba): %s", atendimento, err)


def _limpar(pasta: Path) -> None:
    """Remove a pasta sem lançar: depois de concluir o item, um erro aqui o devolveria à fila."""
    if not pasta.exists():
        return
    try:
        _apagar(pasta)
    except OSError as err:
        log.warning("Não foi possível limpar %s: %s", pasta, err)


def _apagar(pasta: Path) -> None:
    """rmtree que também apaga o que ficou somente leitura (a pasta dos GABs fica com o atributo R depois do Simba)."""

    def liberar(funcao: Callable[[str], object], caminho: str, _: BaseException) -> None:
        os.chmod(caminho, stat.S_IWRITE)
        funcao(caminho)

    shutil.rmtree(pasta, onexc=liberar)


def _configurar_log() -> None:
    pasta = config.LOGS_DIR
    pasta.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter(f"%(asctime)s {config.RUNNER_ID} %(levelname)s %(name)s: %(message)s")
    arquivo = logging.handlers.RotatingFileHandler(
        pasta / "runner.log", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    console = logging.StreamHandler()
    raiz = logging.getLogger()
    # O java-access-bridge-wrapper configura o log raiz ao ser importado; sem isto cada linha sai duplicada.
    raiz.handlers.clear()
    for handler in (arquivo, console):
        handler.setFormatter(formato)
        raiz.addHandler(handler)
    raiz.setLevel(logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--filas",
        default="validador" if config.TRANSMITIR_APOS_VALIDAR else "validador,transmissor",
        help="filas a consumir, separadas por vírgula",
    )
    parser.add_argument("--uma-vez", action="store_true", help="processa no máximo um item e sai")
    parser.add_argument("--lote", type=int, help="processa até N itens do Validador em esteira e sai")
    parser.add_argument("--lista", type=Path, help="JSON com os sys_id dos work items a processar (seleção do console)")
    parser.add_argument("--simular", action="store_true", help="não grava no ServiceNow e não envia (modo simulação)")
    args = parser.parse_args()
    filas = [f.strip() for f in args.filas.split(",") if f.strip()]
    invalidas = [f for f in filas if f not in FILAS]
    if invalidas:
        parser.error(f"filas desconhecidas: {invalidas} (use {', '.join(FILAS)})")
    if config.TRANSMITIR_APOS_VALIDAR and "transmissor" in filas:
        # O mesmo atendimento seria transmitido duas vezes: pelo item do Validador e pelo do Transmissor.
        parser.error(
            "com SIMBA_TRANSMITIR_APOS_VALIDAR=1 o Validador já transmite; não consuma também a fila do Transmissor "
            "(use --filas validador)"
        )
    if not (config.SN_INSTANCIA and config.SN_USUARIO and config.SN_SENHA):
        parser.error("defina SN_INSTANCIA, SN_USUARIO e SN_SENHA (.env)")

    _configurar_log()
    sn = ServiceNow(config.SN_INSTANCIA, config.SN_USUARIO, config.SN_SENHA)
    if args.lote or args.lista:
        _executar_lote(sn, args.lote, args.lista, args.simular)
        return
    if args.simular:
        parser.error("--simular só com --lote ou --lista")
    log.info("Runner %s consumindo %s", config.RUNNER_ID, ", ".join(FILAS[f] for f in filas))
    Runner(sn, filas).executar(uma_vez=args.uma_vez)


def _executar_lote(sn: ServiceNow, max_itens: Optional[int], lista: Optional[Path], simular: bool) -> None:
    """Lote em esteira com andamento para o console: a lista do console ou até `max_itens` itens da fila."""
    sys_ids = json.loads(lista.read_text(encoding="utf-8")) if lista else None
    total = len(sys_ids) if sys_ids is not None else max_itens
    if simular:
        sn, pasta = simulacao.ativar(Runner)
        log.info("SIMULAÇÃO: nada é gravado no ServiceNow nem enviado; arquivos em %s", pasta)
    runner = Runner(sn, ["validador"])
    if simular:
        # O reaper gravaria nos itens presos de outros robôs.
        runner._ultimo_reaper = time.monotonic()
    runner.andamento = Andamento(total, simular)
    log.info("Runner %s: %d item(ns) de Simba Validador em esteira", config.RUNNER_ID, total)
    try:
        log.info("%s", runner.processar_lote(total, sys_ids))
    except BaseException as err:
        runner.andamento.encerrar(f"{type(err).__name__}: {err}")
        raise
    runner.andamento.encerrar()


def executar_uma_vez(filas: list[str], max_itens: int = 1) -> dict[str, object]:
    """Inicializa o runner, processa até `max_itens` itens e encerra os aplicativos Simba.

    Com mais de um item, só a fila do Validador, em esteira (Runner.processar_lote).
    """
    if max_itens < 1:
        raise ValueError("max_itens deve ser ao menos 1")
    if max_itens > 1 and filas != ["validador"]:
        raise ValueError("vários itens por execução só na fila do Validador (filas=['validador'])")
    invalidas = [f for f in filas if f not in FILAS]
    if invalidas:
        raise ValueError(f"filas desconhecidas: {invalidas} (use {', '.join(FILAS)})")
    if not filas:
        raise ValueError("informe ao menos uma fila")
    if config.TRANSMITIR_APOS_VALIDAR and "transmissor" in filas:
        raise ValueError(
            "com SIMBA_TRANSMITIR_APOS_VALIDAR=1 o Validador já transmite; não consuma também a fila do Transmissor"
        )
    if not (config.SN_INSTANCIA and config.SN_USUARIO and config.SN_SENHA):
        raise ValueError("defina SN_INSTANCIA, SN_USUARIO e SN_SENHA (.env)")

    _configurar_log()
    sn = ServiceNow(config.SN_INSTANCIA, config.SN_USUARIO, config.SN_SENHA)
    runner = Runner(sn, filas)
    try:
        log.info(
            "Runner %s processando até %d item(ns) de %s", config.RUNNER_ID, max_itens, ", ".join(FILAS[f] for f in filas)
        )
        return runner.processar_lote(max_itens) if max_itens > 1 else runner.processar_um_item()
    finally:
        runner.app_validador.kill()
        runner.app_transmissor.kill()


if __name__ == "__main__":
    main()
