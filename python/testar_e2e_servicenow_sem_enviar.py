"""Executa o E2E real usando dados e GABs do ServiceNow, sem transmitir.

O script faz somente GET no ServiceNow. Ele baixa o JSON do caso e os anexos
de entrada, executa o Validador, prepara o Transmissor e para quando ``Enviar``
fica habilitado. Não usa a fila, não altera registros e não chama ``Enviar``.

Credenciais do ServiceNow vêm do .env; a chave do órgão vem do CSV de chaves (SIMBA_CHAVES_CSV), como no
runner, ou de --chave e --senha.

    python testar_e2e_servicenow_sem_enviar.py --numero JUDTASK0000001

O ``sys_id`` da JUDTASK pode ser substituído por ``--numero`` para localizar
uma tarefa pela coluna ``number``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


PYTHON_DIR = Path(__file__).resolve().parent
TABELA_TAREFAS = "x_xpi_ofj_judicial_office_task"
GERADOS_PELO_SIMBA = ("_ATENDIMENTO.txt", "_INVESTIGADO.txt", "_corrigido.txt")


class TesteServiceNowError(RuntimeError):
    """Erro de configuração ou de dados que impede o teste seguro."""


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _arquivo_de_entrada(nome: str, atendimento: str) -> bool:
    nome = Path(nome).name
    if not nome.lower().endswith(".txt") or nome.endswith(GERADOS_PELO_SIMBA):
        return False
    if nome.startswith(f"{atendimento}_"):
        return True
    # O ServiceNow pode preservar o nome original do arquivo sem o prefixo do atendimento.
    return re.search(r"(?:^|[_-])GAB\d{3}(?:[_-].*)?\.txt$", nome, re.IGNORECASE) is not None


def _carregar_json_tarefa(sn: Any, identificador: str, por_numero: bool) -> tuple[str, dict[str, Any]]:
    campos = "sys_id,number,description,request_content"
    if por_numero:
        tarefas = sn.listar(TABELA_TAREFAS, f"number={identificador}", campos, limite=10)
        if not tarefas:
            raise TesteServiceNowError(f"Nenhuma JUDTASK encontrada com number={identificador}")
        if len(tarefas) > 1:
            raise TesteServiceNowError(f"Mais de uma JUDTASK encontrada com number={identificador}")
        tarefa = tarefas[0]
    else:
        tarefa = sn.obter(TABELA_TAREFAS, identificador, campos)

    conteudo = _texto(tarefa.get("request_content")) or _texto(tarefa.get("description"))
    if not conteudo:
        raise TesteServiceNowError(
            f"A JUDTASK {tarefa.get('number') or tarefa.get('sys_id')} não possui request_content nem description"
        )
    try:
        dados = json.loads(conteudo)
    except json.JSONDecodeError as erro:
        raise TesteServiceNowError(f"JSON inválido na JUDTASK {tarefa.get('number')}: {erro}") from erro
    if not isinstance(dados, dict):
        raise TesteServiceNowError("O JSON da JUDTASK precisa ser um objeto")
    return _texto(tarefa["sys_id"]), dados


def _baixar_gabs(sn: Any, judtask: str, atendimento: str, destino: Path) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=False)
    anexos = sn.anexos(TABELA_TAREFAS, judtask)
    entradas = [a for a in anexos if _arquivo_de_entrada(_texto(a.get("file_name")), atendimento)]
    if not entradas:
        nomes = ", ".join(sorted(_texto(a.get("file_name")) for a in anexos)) or "<nenhum anexo>"
        raise TesteServiceNowError(
            f"A JUDTASK {judtask} não possui GABs de entrada para {atendimento}. "
            f"Anexos retornados: {nomes}"
        )

    baixados: list[Path] = []
    for anexo in entradas:
        nome = Path(_texto(anexo.get("file_name"))).name
        if not nome or nome != _texto(anexo.get("file_name")):
            raise TesteServiceNowError(f"Nome de anexo inseguro no ServiceNow: {anexo.get('file_name')!r}")
        baixados.append(sn.baixar_anexo({**anexo, "file_name": nome}, destino))
    return baixados


def _chave_e_senha(config: Any, caso: Any, chave_arg: str | None, senha_arg: str | None) -> tuple[Path, str]:
    """--chave/--senha ou, por padrão, a chave do órgão no CSV de chaves (mesma regra do runner)."""
    from simba import chaves

    if chave_arg and senha_arg:
        return Path(chave_arg), senha_arg
    try:
        return chaves.da_orgao(chaves.orgao_do_atendimento(caso.pasta))
    except chaves.ChaveIndisponivel as erro:
        raise TesteServiceNowError(f"{erro}. Informe --chave e --senha.") from erro


def executar(args: argparse.Namespace) -> None:
    if bool(args.judtask) == bool(args.numero):
        raise TesteServiceNowError("Informe exatamente um entre --judtask e --numero.")

    sys.path.insert(0, str(PYTHON_DIR))
    from simba import arquivo, config, fluxo, transmissao
    from simba.app import SimbaApp, TRANSMISSOR, VALIDADOR
    from simba.cadastro import Caso
    from simba.servicenow import ServiceNow

    if not config.SN_INSTANCIA or not config.SN_USUARIO or not config.SN_SENHA:
        raise TesteServiceNowError("Configure SN_INSTANCIA, SN_USUARIO e SN_SENHA no ambiente/.env.")

    sn = ServiceNow(config.SN_INSTANCIA, config.SN_USUARIO, config.SN_SENHA)
    judtask, dados = _carregar_json_tarefa(sn, args.judtask or args.numero, bool(args.numero))
    dados["Judtask"] = dados.get("Judtask") or judtask
    caso = Caso.from_json(dados)

    base = Path(args.work_dir) if args.work_dir else config.TRABALHO_DIR / "teste-e2e-servicenow"
    pasta_caso = base / caso.pasta
    if pasta_caso.exists():
        raise TesteServiceNowError(
            f"A pasta de trabalho já existe: {pasta_caso}. "
            "Use outro --work-dir ou remova a pasta após conferir os artefatos."
        )
    pasta_caso.mkdir(parents=True, exist_ok=False)
    (pasta_caso / "caso_servicenow.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pasta_gabs = pasta_caso / "gabs"
    baixados = _baixar_gabs(sn, judtask, caso.pasta, pasta_gabs)
    print(f"[1/4] ServiceNow OK: {len(baixados)} GAB(s) baixado(s) em {pasta_gabs}")
    print(f"      JUDTASK: {judtask}; atendimento: {caso.pasta}")

    if args.nao_executar_validador:
        print("[2/4] Validador ignorado por --nao-executar-validador.")
        return

    validador = SimbaApp(VALIDADOR)
    try:
        resultado = fluxo.processar(validador, caso, pasta_gabs)
    finally:
        validador.kill()
    print(f"[2/4] Validador OK: {resultado.pacote}")
    print(f"      Hash: {resultado.hash}")

    arquivo.sincronizar_transmissor(caso.pasta)
    chave, senha = (None, None) if args.sem_chave else _chave_e_senha(config, caso, args.chave, args.senha)
    transmissor = SimbaApp(TRANSMISSOR)
    try:
        transmissor.ensure_ready()
        situacao = transmissao.selecionar_atendimento(transmissor, caso.pasta)
        if args.sem_chave:
            print(f"[3/4] Transmissor OK: {situacao}")
            print("[4/4] PARADO COM SEGURANÇA (--sem-chave): atendimento selecionado; chave não carregada.")
            print(f"      Artefatos locais: {pasta_caso}")
            return
        transmissao.carregar_chave(transmissor, chave, senha)
        print(f"[3/4] Transmissor OK: {situacao}")
        print("[4/4] PARADO COM SEGURANÇA: Enviar está habilitado, mas não foi clicado.")
        print(f"      Artefatos locais: {pasta_caso}")
    finally:
        transmissor.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--judtask", help="sys_id da JUDTASK no ServiceNow")
    grupo.add_argument("--numero", help="number da JUDTASK no ServiceNow")
    parser.add_argument("--chave", help="arquivo de chave .ASB; por padrão usa SIMBA_CHAVE_<órgão>")
    parser.add_argument("--senha", help="senha da chave; por padrão usa SIMBA_SENHA_<NOME>")
    parser.add_argument("--work-dir", help="pasta raiz dos artefatos baixados")
    parser.add_argument(
        "--sem-chave",
        action="store_true",
        help="para no Transmissor depois de selecionar o atendimento, sem carregar chave/senha",
    )
    parser.add_argument(
        "--nao-executar-validador",
        action="store_true",
        help="somente baixar e organizar os dados; não abre o Simba",
    )
    args = parser.parse_args()
    try:
        executar(args)
    except Exception as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
