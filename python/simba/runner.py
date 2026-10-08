"""Runner: consome as filas Simba Validador e Simba Transmissor do RPA Hub, um work item por vez.

Cada runner é uma sessão Windows com o Simba instalado; vários runners rodam em paralelo sem estado próprio:
tudo vem do ServiceNow (JSON, anexos) e volta para ele (anexos, status do work item).

Uso: python -m simba.runner [--filas validador,transmissor] [--uma-vez]
"""
import argparse
import json
import logging
import logging.handlers
import os
import re
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from simba import arquivo, config, fluxo, notificacao
from simba.app import TRANSMISSOR, VALIDADOR, SimbaApp, SimbaAviso, StepFailed
from simba.cadastro import Caso
from simba.fila import Fila, Item, ReservaPerdida
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


def nome_variavel_senha(chave: str) -> str:
    """Variável do .env com a senha do arquivo de chaves: SIMBA_SENHA_<nome do arquivo sem extensão>."""
    return "SIMBA_SENHA_" + re.sub(r"\W", "_", Path(chave).stem).upper()


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

    def _executar_item(self, handler: Callable[[Fila, Item, Path], None], fila: Fila, item: Item, pasta: Path) -> None:
        """Roda o handler; qualquer parada vira status no work item + comentário na JUDTASK."""
        try:
            handler(fila, item, pasta)
            return
        except ReservaPerdida as err:
            # Outro runner (ou o reaper) assumiu o item; quem assumiu registra o que acontecer.
            log.warning("%s", err)
            return
        except (SimbaAviso, DadosInvalidos) as err:
            erro, tipo, orientacao = getattr(err, "message", str(err)), "business", notificacao.NEGOCIO
        except (TransmissaoIncerta, AcaoManual) as err:
            erro, tipo, orientacao = str(err), "application", notificacao.MANUAL
        except (StepFailed, ServiceNowError, OSError) as err:
            erro, tipo, orientacao = str(err), None, None
        except Exception as err:
            # Erro inesperado: registra e devolve (conta tentativa) em vez de derrubar o runner.
            log.exception("Erro inesperado em %s", item.nome)
            erro, tipo, orientacao = f"{type(err).__name__}: {err}", None, None

        try:
            if tipo is None:
                status = fila.devolver(item, erro)
                orientacao = notificacao.NOVA_TENTATIVA if status == "pending" else notificacao.MANUAL
            else:
                fila.falhar(item, tipo, erro)
        except (ServiceNowError, ReservaPerdida):
            # Sem conseguir atualizar o work item, o reaper o recolhe depois do lease (e comenta).
            log.exception("Não foi possível registrar a falha de %s no work item", item.nome)
            return
        parada = notificacao.Parada(
            fila.nome, item.nome, item.etapa, item.tentativa, orientacao, erro, config.RUNNER_ID, self._passo_simba()
        )
        self._comentar(parada, item.judtask, item.request)

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
        try:
            dados = self._dados_validador(item)
            item.judtask = dados.get("Judtask")
            caso = Caso.from_json(dados)
            judtask = dados["Judtask"]
        except (ValueError, KeyError, AttributeError) as err:
            raise DadosInvalidos(f"JSON do caso inválido ou incompleto: {err!r}") from err
        if config.TRANSMITIR_APOS_VALIDAR:
            tarefa = self.sn.obter(TABELA_TAREFAS, judtask, "number,evidence_attachment")
            if tarefa["evidence_attachment"]:
                # Anti-duplicidade: o comprovante só é gravado depois de um envio bem-sucedido.
                fila.concluir(item, f"Comprovante já registrado em {tarefa['number']}; atendimento não reenviado")
                return
        try:
            self._validar(fila, item, pasta, caso, judtask)
        finally:
            # Sucesso ou falha: o atendimento sai das listas do Simba (os programas precisam estar fechados).
            self.app_validador.kill()
            self.app_transmissor.kill()
            _arquivar(caso.pasta)

    def _validar(self, fila: Fila, item: Item, pasta: Path, caso: Caso, judtask: str) -> None:
        fila.etapa(item, "baixando")
        arquivos = pasta / caso.pasta
        arquivos.mkdir()
        # Só os arquivos de entrada: a tarefa também guarda a saída de execuções anteriores (pacote, base do Simba).
        anexos = [a for a in self.sn.anexos(TABELA_TAREFAS, judtask) if _arquivo_de_entrada(a["file_name"], caso.pasta)]
        if not anexos:
            raise DadosInvalidos(f"Tarefa {judtask} sem arquivos {caso.pasta}_*.txt para validar")
        for anexo in anexos:
            self.sn.baixar_anexo(anexo, arquivos)

        fila.etapa(item, "validando")
        resultado = fluxo.processar(self.app_validador, caso, arquivos)

        fila.etapa(item, "anexando")
        self._anexar_pasta(judtask, arquivo.dados_validador(caso.pasta), arquivos)
        resposta = f"{caso.pasta} validado e gerado; hash {resultado.hash}"
        if resultado.correcoes:
            # Auditoria: o que mudou nos arquivos validados (as cópias corrigidas vão como *_corrigido).
            notificacao.registrar_correcoes(self.sn, judtask, fila.nome, item.nome, resultado.correcoes)
            resposta += f"; {len(resultado.correcoes)} correção(ões) automática(s) nos arquivos"

        if config.TRANSMITIR_APOS_VALIDAR:
            # Transmite já com o pacote gerado nesta máquina, sem esperar a tarefa/fila do Transmissor.
            fila.etapa(item, "preparando_envio")
            chave, senha = self._chave_e_senha(self._chave_da_instituicao(caso.cnpj))
            # O Transmissor só lê a lista de atendimentos ao abrir.
            self.app_transmissor.kill()
            transmitido = fluxo.transmitir(
                self.app_transmissor,
                caso.pasta,
                arquivos,
                chave,
                senha,
                antes_de_enviar=lambda: fila.etapa(item, "enviando"),
            )
            fila.etapa(item, "registrando")
            self._registrar_comprovante(judtask, transmitido)
            resposta += f"; transmitido: {transmitido.mensagem}"
        fila.concluir(item, resposta)

    def _anexar_pasta(self, judtask: str, pasta: Path, originais: Path) -> None:
        """Sobe a saída do Validador (pasta e subpastas de primeiro nível, como o Uploads do .iBot).

        Arquivos gerados (pacote, hash, base do Simba) substituem os de mesmo nome já anexados: num
        reprocessamento o pacote é regerado e o anexo antigo ficaria desatualizado. Cópias dos arquivos de entrada
        (os GABs em arqtxt) nunca apagam os originais da tarefa: só sobem se diferirem (correção automática),
        com o sufixo _corrigido.
        """
        anexados: dict[str, list[dict]] = {}
        for anexo in self.sn.anexos(TABELA_TAREFAS, judtask):
            anexados.setdefault(anexo["file_name"], []).append(anexo)
        arquivos = [p for p in pasta.iterdir() if p.is_file()]
        arquivos += [p for sub in pasta.iterdir() if sub.is_dir() for p in sub.iterdir() if p.is_file()]
        for gerado in arquivos:
            original = originais / gerado.name
            if original.is_file():
                if gerado.read_bytes() == original.read_bytes():
                    continue
                # Cópia na pasta de trabalho: o dadosValidador vai intacto para o arquivo.
                corrigidos = originais.parent / "corrigidos"
                corrigidos.mkdir(exist_ok=True)
                gerado = Path(shutil.copy2(gerado, corrigidos / f"{gerado.stem}_corrigido{gerado.suffix}"))
            for antigo in anexados.get(gerado.name, []):
                self.sn.excluir_anexo(antigo["sys_id"])
            self.sn.anexar(TABELA_TAREFAS, judtask, gerado)

    def _chave_da_instituicao(self, cnpj: str) -> str:
        """Nome do arquivo de chaves da instituição do caso (SIMBA_CHAVE_<CNPJ só com dígitos> no .env)."""
        variavel = "SIMBA_CHAVE_" + re.sub(r"\D", "", cnpj)
        nome = os.environ.get(variavel)
        if not nome:
            raise AcaoManual(f"Arquivo de chaves da instituição CNPJ {cnpj} não configurado ({variavel} no .env)")
        return nome

    def _chave_e_senha(self, nome_chave: str) -> tuple[Path, str]:
        chave = config.CHAVES_DIR / nome_chave
        variavel = nome_variavel_senha(nome_chave)
        senha = os.environ.get(variavel)
        if not chave.is_file():
            raise AcaoManual(f"Arquivo de chaves não encontrado no runner: {chave}")
        if not senha:
            raise AcaoManual(f"Senha da chave {nome_chave} não configurada ({variavel} no .env)")
        return chave, senha

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
            judtask, atendimento, nome_chave = dados["Judtask"], dados["Simba"], dados["Chave"]
        except (ValueError, KeyError, AttributeError) as err:
            raise DadosInvalidos(f"Work item do Transmissor inválido: {err!r}") from err

        tarefa = self.sn.obter(TABELA_TAREFAS, judtask, "number,evidence_attachment")
        if tarefa["evidence_attachment"]:
            # Anti-duplicidade: o comprovante só é gravado depois de um envio bem-sucedido.
            fila.concluir(item, f"Comprovante já registrado em {tarefa['number']}; atendimento não reenviado")
            return

        chave, senha = self._chave_e_senha(nome_chave)
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
        envio = arquivo.dados_validador(atendimento) / "envio"
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
        shutil.rmtree(pasta)
    except OSError as err:
        log.warning("Não foi possível limpar %s: %s", pasta, err)


def _configurar_log() -> None:
    pasta = config.SIMBA_HOME / "logs"
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
        parser.error("defina SN_INSTANCIA, SN_USUARIO e SN_SENHA (python/.env)")

    _configurar_log()
    sn = ServiceNow(config.SN_INSTANCIA, config.SN_USUARIO, config.SN_SENHA)
    log.info("Runner %s consumindo %s", config.RUNNER_ID, ", ".join(FILAS[f] for f in filas))
    Runner(sn, filas).executar(uma_vez=args.uma_vez)


if __name__ == "__main__":
    main()
