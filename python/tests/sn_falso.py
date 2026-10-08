"""ServiceNow em memória para exercitar o runner com o Simba real sem tocar em nenhuma instância.

Conta as requisições por tipo e passa pelo mesmo limitador do cliente real (servicenow._cadenciar).
"""
import json
import shutil
import uuid
from collections import Counter
from pathlib import Path

from simba import servicenow
from simba.cadastro import Caso
from simba.fila import TABELA
from simba.servicenow import TABELA_TAREFAS, agora_utc, formatar_data


class ServiceNowFalso:
    def __init__(self, fila: str) -> None:
        self.fila = fila
        self.requisicoes: Counter[str] = Counter()
        self.itens: dict[str, dict[str, str]] = {}
        self.tarefas: dict[str, dict[str, str]] = {}
        self.anexos_por: dict[tuple[str, str], list[dict[str, str]]] = {}
        self.conteudo: dict[str, Path] = {}

    def _contar(self, tipo: str) -> None:
        servicenow._cadenciar()
        self.requisicoes[tipo] += 1

    # --- montagem dos casos ---------------------------------------------------

    def adicionar_caso(self, caso: Caso, dados: dict, gabs: Path) -> str:
        judtask = uuid.uuid4().hex
        self.tarefas[judtask] = {"sys_id": judtask, "number": f"JUDTASK{len(self.tarefas):07d}"}
        for gab in sorted(gabs.iterdir()):
            self._guardar(TABELA_TAREFAS, judtask, gab)
        sys_id = uuid.uuid4().hex
        self.itens[sys_id] = {
            "sys_id": sys_id,
            "name": f"SimbaValidador_{self.tarefas[judtask]['number']}",
            "status": "pending",
            "locked": "false",
            "remarks": "",
            "stage": "",
            "attempts_count": "0",
            "deferred_till": "",
            "request_content": json.dumps({**dados, "Judtask": judtask}, ensure_ascii=False),
            "sys_updated_on": formatar_data(agora_utc()),
        }
        return sys_id

    def _guardar(self, tabela: str, sys_id: str, arquivo: Path) -> str:
        anexo_id = uuid.uuid4().hex
        self.conteudo[anexo_id] = arquivo
        self.anexos_por.setdefault((tabela, sys_id), []).append(
            {"sys_id": anexo_id, "file_name": arquivo.name, "size_bytes": str(arquivo.stat().st_size), "table_name": tabela}
        )
        return anexo_id

    # --- API usada pelo runner --------------------------------------------------

    def listar(self, tabela: str, query: str, campos: str, limite: int = 100) -> list[dict[str, str]]:
        self._contar("listar")
        if tabela != TABELA:
            return []
        status = "in_progress" if "status=in_progress" in query else "pending"
        encontrados = [
            dict(i)
            for i in self.itens.values()
            if i["status"] == status and (status == "in_progress" or i["locked"] == "false")
        ]
        return encontrados[:limite]

    def obter(self, tabela: str, sys_id: str, campos: str) -> dict[str, str]:
        self._contar("obter")
        return dict(self.itens[sys_id] if tabela == TABELA else self.tarefas[sys_id])

    def atualizar(self, tabela: str, sys_id: str, valores: dict, campos: str = "sys_id") -> dict[str, str]:
        self._contar(f"atualizar {tabela.split('_')[-1]}")
        destino = self.itens[sys_id] if tabela == TABELA else self.tarefas[sys_id]
        destino.update({k: str(v) for k, v in valores.items()})
        if tabela == TABELA:
            destino["sys_updated_on"] = formatar_data(agora_utc())
        return {k: str(v) for k, v in valores.items()}

    def anexos(self, tabela: str, sys_id: str, *outras_tabelas: str) -> list[dict[str, str]]:
        self._contar("anexos")
        return [a for t in (tabela, *outras_tabelas) for a in self.anexos_por.get((t, sys_id), [])]

    def baixar_anexo(self, anexo: dict[str, str], pasta: Path) -> Path:
        self._contar("baixar_anexo")
        return Path(shutil.copy2(self.conteudo[anexo["sys_id"]], pasta / anexo["file_name"]))

    def anexar(self, tabela: str, sys_id: str, arquivo: Path) -> str:
        self._contar("anexar")
        return self._guardar(tabela, sys_id, arquivo)

    def excluir_anexo(self, anexo_sys_id: str) -> None:
        self._contar("excluir_anexo")
        for lista in self.anexos_por.values():
            lista[:] = [a for a in lista if a["sys_id"] != anexo_sys_id]
