"""Processa até cinco itens reais de uma fila ServiceNow, sem transmitir.

O script consulta somente itens pendentes e desbloqueados da fila informada,
baixa os dados da JUDTASK e os GABs, executa o Validador e prepara o
Transmissor até ``Enviar`` ficar habilitado. Ele não reserva itens e não chama
``Enviar``. Com ``--atualizar-falhas``, uma falha coloca a JUDTASK em ``draft``
e grava o erro nos comentários da JUDTASK e da JUD relacionada.

Exemplo no CMD:

    set SN_INSTANCIA=minha-instancia
    set SN_USUARIO=usuario
    set SN_SENHA=senha
    python testar_fila_servicenow_sem_enviar.py ^
      --fila-id 0fae6a06fb55a250a23df6f26eefdc07 ^
      --limite 5
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any


PYTHON_DIR = Path(__file__).resolve().parent
TABELA_FILA = "sn_rpa_fdn_work_queue_item"
TABELA_JUD = "x_xpi_ofj_judicial_office"
TABELA_JUDTASK = "x_xpi_ofj_judicial_office_task"
CAMPOS_FILA = "sys_id,name,status,locked,request_content"
log = logging.getLogger(__name__)


class FilaTesteError(RuntimeError):
    """Erro que impede o processamento seguro da fila de teste."""


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _dados_do_item(sn: Any, item: dict[str, str]) -> tuple[str, dict[str, Any]]:
    request = _texto(item.get("request_content"))
    if request:
        try:
            dados = json.loads(request)
        except json.JSONDecodeError as erro:
            raise FilaTesteError(f"JSON inválido no work item {item.get('name')}: {erro}") from erro
        if not isinstance(dados, dict):
            raise FilaTesteError(f"request_content não é um objeto no work item {item.get('name')}")
        judtask = _texto(dados.get("Judtask"))
        if not judtask:
            raise FilaTesteError(f"request_content sem Judtask no work item {item.get('name')}")
        return judtask, dados

    numero = _texto(item.get("name")).rsplit("_", 1)[-1]
    if not numero.startswith("JUDTASK"):
        raise FilaTesteError(f"Work item {item.get('name')} sem request_content e sem número de JUDTASK")

    from testar_e2e_servicenow_sem_enviar import _carregar_json_tarefa

    return _carregar_json_tarefa(sn, numero, True)


def _comentario_falha(item: dict[str, str], caso: str, erro: Exception) -> str:
    return (
        "[RPA TESTE E2E ServiceNow]\n"
        "O processamento foi interrompido antes da transmissão.\n"
        f"Work item: {_texto(item.get('name'))} ({_texto(item.get('sys_id'))})\n"
        f"Atendimento: {caso or '<não identificado>'}\n"
        f"Erro: {type(erro).__name__}: {erro}\n"
        "A JUDTASK foi colocada em draft para correção dos dados."
    )


def _resolver_jud(sn: Any, judtask: str, dados: dict[str, Any], campo: str) -> str:
    for chave in ("Jud", "JudSysId", "JudicialOffice", "JudicialOfficeSysId"):
        valor = _texto(dados.get(chave))
        if valor:
            return valor
    tarefa = sn.obter(TABELA_JUDTASK, judtask, f"{campo}")
    jud_id = _texto(tarefa.get(campo))
    if not jud_id:
        raise FilaTesteError(
            f"A JUDTASK {judtask} não possui o relacionamento {campo!r} preenchido"
        )
    return jud_id


def _registrar_falha(
    sn: Any,
    item: dict[str, str],
    judtask: str,
    dados: dict[str, Any],
    caso: str,
    erro: Exception,
    campo_jud: str,
) -> None:
    comentario = _comentario_falha(item, caso, erro)
    sn.atualizar(TABELA_JUDTASK, judtask, {"status": "draft", "comments": comentario})
    jud_id = _resolver_jud(sn, judtask, dados, campo_jud)
    sn.atualizar(TABELA_JUD, jud_id, {"comments": comentario})


def executar(args: argparse.Namespace) -> int:
    if not args.fila_id.strip():
        raise FilaTesteError("--fila-id não pode ficar vazio")
    if not 1 <= args.limite <= 5:
        raise FilaTesteError("--limite deve estar entre 1 e 5")

    sys.path.insert(0, str(PYTHON_DIR))
    from simba import arquivo, config, fluxo, transmissao
    from simba.app import SimbaApp, TRANSMISSOR, VALIDADOR
    from simba.cadastro import Caso
    from simba.servicenow import ServiceNow
    from testar_e2e_servicenow_sem_enviar import _baixar_gabs, _chave_e_senha

    if not config.SN_INSTANCIA or not config.SN_USUARIO or not config.SN_SENHA:
        raise FilaTesteError("Configure SN_INSTANCIA, SN_USUARIO e SN_SENHA no ambiente/.env.")

    sn = ServiceNow(config.SN_INSTANCIA, config.SN_USUARIO, config.SN_SENHA)
    query = f"work_queue={args.fila_id.strip()}^status=pending^locked=false^ORDERBYsys_created_on"
    itens = sn.listar(TABELA_FILA, query, CAMPOS_FILA, limite=args.limite)
    if not itens:
        print("Nenhum item pending/unlocked encontrado nessa fila.")
        return 0

    base = Path(args.work_dir) if args.work_dir else config.TRABALHO_DIR / "teste-fila-servicenow"
    staging = Path(args.simba_input_dir or os.getenv("SIMBA_INPUT_DIR") or Path.home() / "RPA_INPUT")
    base.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    print(f"Encontrados {len(itens)} item(ns); limite aplicado: {args.limite}.")
    print("Modo seguro: nenhum item será reservado ou atualizado no ServiceNow.")

    processados = 0
    falhos = 0
    for indice, item in enumerate(itens, start=1):
        item_id = _texto(item.get("sys_id"))
        if not item_id:
            raise FilaTesteError("Item da fila sem sys_id")
        print(f"\n[{indice}/{len(itens)}] Work item: {_texto(item.get('name'))} ({item_id})")
        judtask = ""
        dados: dict[str, Any] = {}
        caso_nome = ""
        try:
            judtask, dados = _dados_do_item(sn, item)
            dados["Judtask"] = dados.get("Judtask") or judtask
            caso = Caso.from_json(dados)
            caso_nome = caso.pasta
            pasta_item = base / f"{item_id}_{caso.pasta}"
            if pasta_item.exists():
                raise FilaTesteError(
                    f"A pasta de trabalho já existe: {pasta_item}. "
                    "Use outro --work-dir ou remova a pasta após conferir os artefatos."
                )
            pasta_item.mkdir()
            (pasta_item / "caso_servicenow.json").write_text(
                json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            gabs = pasta_item / "gabs"
            baixados = _baixar_gabs(sn, judtask, caso.pasta, gabs)
            print(f"      {len(baixados)} GAB(s) baixado(s).")
            pasta_simba = staging / f"{item_id}_{caso.pasta}"
            if pasta_simba.exists():
                raise FilaTesteError(f"A pasta curta de entrada já existe: {pasta_simba}")
            shutil.copytree(gabs, pasta_simba)
            print(f"      Pasta usada pelo Simba: {pasta_simba}")

            validador = SimbaApp(VALIDADOR)
            try:
                resultado = fluxo.processar(validador, caso, pasta_simba)
            finally:
                validador.kill()
            print(f"      Validador OK; hash={resultado.hash}")

            arquivo.sincronizar_transmissor(caso.pasta)
            if not args.sem_chave:
                chave, senha = _chave_e_senha(config, caso, args.chave, args.senha)
            transmissor = SimbaApp(TRANSMISSOR)
            try:
                transmissor.ensure_ready()
                situacao = transmissao.selecionar_atendimento(transmissor, caso.pasta)
                if args.sem_chave:
                    print(f"      Transmissor: {situacao}")
                    print("      PARADO (--sem-chave): atendimento selecionado; chave não carregada.")
                else:
                    transmissao.carregar_chave(transmissor, chave, senha)
                    print(f"      Transmissor preparado: {situacao}")
                    print("      PARADO ANTES DE ENVIAR: nenhum clique em Enviar foi executado.")
            finally:
                transmissor.kill()
            processados += 1
        except Exception as erro:
            falhos += 1
            print(f"      FALHOU: {erro}", file=sys.stderr)
            if args.atualizar_falhas:
                try:
                    _registrar_falha(sn, item, judtask, dados, caso_nome, erro, args.campo_jud)
                    print("      ServiceNow atualizado: JUDTASK=draft; comentário gravado na JUDTASK e na JUD.")
                except Exception as atualizacao:
                    print(f"      ERRO ao registrar falha no ServiceNow: {atualizacao}", file=sys.stderr)
            else:
                print("      Nenhuma alteração foi feita no ServiceNow (use --atualizar-falhas para registrar).")

    print(
        f"\nTeste concluído: {processados} item(ns) preparado(s), "
        f"{falhos} item(ns) com falha, sem transmissão."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fila-id", required=True, help="sys_id da fila no ServiceNow")
    parser.add_argument("--limite", type=int, default=5, help="quantidade máxima de itens (1 a 5)")
    parser.add_argument("--chave", help="arquivo de chave .ASB comum aos casos, se aplicável")
    parser.add_argument("--senha", help="senha da chave comum, se aplicável")
    parser.add_argument("--work-dir", help="pasta raiz dos artefatos baixados")
    parser.add_argument(
        "--sem-chave",
        action="store_true",
        help="para no Transmissor depois de selecionar o atendimento, sem carregar chave/senha",
    )
    parser.add_argument(
        "--simba-input-dir",
        help="pasta curta usada pelo diálogo do Simba (padrão: SIMBA_INPUT_DIR ou RPA_INPUT no perfil do usuário)",
    )
    parser.add_argument(
        "--atualizar-falhas",
        action="store_true",
        help="em cada falha, coloca a JUDTASK em draft e grava comentário na JUDTASK e na JUD",
    )
    parser.add_argument(
        "--campo-jud",
        default=os.getenv("SN_JUDTASK_JUD_FIELD", "judicial_office"),
        help="campo referência da JUD na JUDTASK (padrão: judicial_office)",
    )
    args = parser.parse_args()
    try:
        return executar(args)
    except Exception as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
