"""Cliente REST do ServiceNow (Table API + Attachment API) com usuário de integração (basic auth)."""
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from simba import config

log = logging.getLogger(__name__)

TABELA_TAREFAS = "x_xpi_ofj_judicial_office_task"
TIMEOUT = 30
DOWNLOAD_TIMEOUT = 300
# GET e PATCH são idempotentes e podem ser repetidos em falha de rede/429/5xx; POST de anexo não.
TENTATIVAS = 3
STATUS_TEMPORARIOS = {429, 500, 502, 503, 504}


class ServiceNowError(Exception):
    pass


# O usuário de integração é bloqueado acima de 100 requisições/minuto. Toda requisição do processo (inclusive o
# heartbeat, em outra thread) respeita um intervalo mínimo; com N runners no mesmo usuário, divida o valor por N.
_intervalo = 60 / config.SN_REQUISICOES_POR_MINUTO
_cadencia = threading.Lock()
_proxima = 0.0


def _cadenciar() -> None:
    global _proxima
    with _cadencia:
        agora = time.monotonic()
        if _proxima > agora:
            time.sleep(_proxima - agora)
        _proxima = max(agora, _proxima) + _intervalo


def normalizar_instancia(url: str) -> str:
    """Aceita "empresa", "empresa.service-now.com" ou a URL completa; devolve "https://host"."""
    url = url.strip().rstrip("/")
    if not url:
        raise ValueError("Informe a instância do ServiceNow")
    if "://" not in url:
        url = "https://" + (url if "." in url else f"{url}.service-now.com")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"URL de instância inválida: {url}")
    return f"https://{parsed.hostname}"


def agora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def formatar_data(dt: datetime) -> str:
    """Data/hora no formato interno do SN (UTC), usado com sysparm_display_value=false."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ler_data(valor: str) -> Optional[datetime]:
    return datetime.strptime(valor, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if valor else None


class ServiceNow:
    def __init__(self, instancia: str, usuario: str, senha: str) -> None:
        self.instancia = normalizar_instancia(instancia)
        self.session = requests.Session()
        self.session.auth = (usuario, senha)
        self.session.headers["Accept"] = "application/json"
        # O runner usa o cliente em mais de uma thread (heartbeat, esteira) e a requests.Session não é thread-safe.
        self._lock = threading.RLock()

    def _request(self, metodo: str, path: str, repetir: bool = True, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", TIMEOUT)
        tentativas = TENTATIVAS if repetir else 1
        for tentativa in range(1, tentativas + 1):
            espera = 2**tentativa
            _cadenciar()
            try:
                with self._lock:
                    resp = self.session.request(metodo, self.instancia + path, allow_redirects=False, **kwargs)
            except requests.RequestException as err:
                if tentativa == tentativas:
                    raise ServiceNowError(f"Falha de conexão com {self.instancia}: {err}") from err
                log.warning("%s %s: %s (tentativa %d)", metodo, path, err, tentativa)
            else:
                if resp.status_code not in STATUS_TEMPORARIOS or tentativa == tentativas:
                    break
                log.warning("%s %s: HTTP %d (tentativa %d)", metodo, path, resp.status_code, tentativa)
                if resp.status_code == 429:
                    # Limite de requisições do SN: espera o que ele pedir, no mínimo um minuto.
                    espera = max(60, int(resp.headers.get("Retry-After", "0") or 0))
            time.sleep(espera)
        if resp.is_redirect:
            raise ServiceNowError(f"Redirecionado para {resp.headers.get('Location')} (credencial inválida?)")
        if resp.status_code in (401, 403):
            raise ServiceNowError(f"Acesso negado ({resp.status_code}) em {path}: {_mensagem_erro(resp)}")
        if not 200 <= resp.status_code < 300:
            raise ServiceNowError(f"HTTP {resp.status_code} em {metodo} {path}: {_mensagem_erro(resp)}")
        return resp

    # --- Table API -------------------------------------------------------

    def listar(self, tabela: str, query: str, campos: str, limite: int = 100) -> list[dict[str, str]]:
        params = {"sysparm_query": query, "sysparm_fields": campos, "sysparm_limit": limite}
        return self._request("GET", f"/api/now/table/{tabela}", params=params).json()["result"]

    def listar_todos(self, tabela: str, query: str, campos: str, pagina: int = 1000) -> list[dict[str, str]]:
        """Todos os registros da query, `pagina` por requisição (sysparm_offset)."""
        registros: list[dict[str, str]] = []
        while True:
            params = {
                "sysparm_query": query,
                "sysparm_fields": campos,
                "sysparm_limit": pagina,
                "sysparm_offset": len(registros),
            }
            lote = self._request("GET", f"/api/now/table/{tabela}", params=params).json()["result"]
            registros += lote
            if len(lote) < pagina:
                return registros

    def obter(self, tabela: str, sys_id: str, campos: str) -> dict[str, str]:
        return self._request("GET", f"/api/now/table/{tabela}/{sys_id}", params={"sysparm_fields": campos}).json()[
            "result"
        ]

    def atualizar(self, tabela: str, sys_id: str, valores: dict[str, Any], campos: str = "sys_id") -> dict[str, str]:
        resp = self._request(
            "PATCH", f"/api/now/table/{tabela}/{sys_id}", params={"sysparm_fields": campos}, json=valores
        )
        return resp.json()["result"]

    def criar(self, tabela: str, valores: dict[str, Any]) -> dict[str, str]:
        return self._request("POST", f"/api/now/table/{tabela}", repetir=False, json=valores).json()["result"]

    def excluir(self, tabela: str, sys_id: str) -> None:
        self._request("DELETE", f"/api/now/table/{tabela}/{sys_id}")

    # --- Attachment API --------------------------------------------------

    def anexos(self, tabela: str, sys_id: str, *outras_tabelas: str) -> list[dict[str, str]]:
        """Anexos do registro; `outras_tabelas` (ex.: ZZ_YY<tabela> dos campos file_attachment) na mesma requisição."""
        tabelas = ",".join((tabela, *outras_tabelas))
        params = {
            "sysparm_query": f"table_nameIN{tabelas}^table_sys_id={sys_id}",
            "sysparm_fields": "sys_id,file_name,size_bytes,table_name",
        }
        return self._request("GET", "/api/now/attachment", params=params).json()["result"]

    def baixar_anexo(self, anexo: dict[str, str], pasta: Path) -> Path:
        """Grava o anexo em `pasta` (streaming) e confere o tamanho."""
        destino = pasta / anexo["file_name"]
        # A conexão fica presa à resposta até o fim do streaming: nenhuma outra thread usa a sessão enquanto isso.
        with self._lock:
            resp = self._request(
                "GET", f"/api/now/attachment/{anexo['sys_id']}/file", stream=True, timeout=DOWNLOAD_TIMEOUT
            )
            with destino.open("wb") as f:
                for bloco in resp.iter_content(1024 * 1024):
                    f.write(bloco)
        # Anexo vazio (ex.: GAB109 sem movimentação) vem com size_bytes "".
        if destino.stat().st_size != int(anexo["size_bytes"] or 0):
            raise ServiceNowError(f"Download incompleto de {anexo['file_name']}: {destino.stat().st_size} bytes")
        return destino

    def excluir_anexo(self, anexo_sys_id: str) -> None:
        self._request("DELETE", f"/api/now/attachment/{anexo_sys_id}")

    def anexar(self, tabela: str, sys_id: str, arquivo: Path) -> str:
        """Sobe `arquivo` como anexo do registro e devolve o sys_id do anexo."""
        params = {"table_name": tabela, "table_sys_id": sys_id, "file_name": arquivo.name}
        with arquivo.open("rb") as f:
            resp = self._request(
                "POST",
                "/api/now/attachment/file",
                repetir=False,
                params=params,
                data=f,
                headers={"Content-Type": "application/octet-stream"},
                timeout=DOWNLOAD_TIMEOUT,
            )
        return resp.json()["result"]["sys_id"]


def _mensagem_erro(resp: requests.Response) -> str:
    try:
        erro = resp.json().get("error") or {}
        return erro.get("message") or erro.get("detail") or resp.reason
    except ValueError:
        return resp.reason
