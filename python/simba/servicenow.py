"""Cliente REST do ServiceNow.

Duas formas de autenticar:
- sessão do navegador (SSO): cookies da sessão + token `g_ck` no cabeçalho X-UserToken;
- basic auth: usuário com senha local na instância.
"""
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests

TABELA_TAREFAS = "x_xpi_ofj_judicial_office_task"
TIMEOUT = 30


class ServiceNowError(Exception):
    pass


@dataclass
class Usuario:
    sys_id: str
    user_name: str
    nome: str


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


class ServiceNow:
    def __init__(self, instancia: str, session: requests.Session) -> None:
        self.instancia = instancia
        self.session = session
        self.session.headers["Accept"] = "application/json"

    @classmethod
    def por_sessao(cls, instancia: str, cookies: dict[str, str], user_token: str) -> "ServiceNow":
        session = requests.Session()
        host = urlparse(instancia).hostname
        for nome, valor in cookies.items():
            session.cookies.set(nome, valor, domain=host)
        session.headers["X-UserToken"] = user_token
        return cls(instancia, session)

    @classmethod
    def por_basic_auth(cls, instancia: str, usuario: str, senha: str) -> "ServiceNow":
        session = requests.Session()
        session.auth = (usuario, senha)
        return cls(instancia, session)

    def _get(self, path: str, params: Optional[dict] = None) -> requests.Response:
        try:
            resp = self.session.get(self.instancia + path, params=params, timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as err:
            raise ServiceNowError(f"Falha de conexão com {self.instancia}: {err}") from err
        if resp.is_redirect:
            # A instância manda para a tela de login quando a sessão expirou.
            raise ServiceNowError(f"Sessão expirada ou inválida (redirecionado para {resp.headers.get('Location')})")
        if resp.status_code in (401, 403):
            raise ServiceNowError(f"Acesso negado ({resp.status_code}) em {path}: {_mensagem_erro(resp)}")
        if resp.status_code != 200:
            raise ServiceNowError(f"HTTP {resp.status_code} em {path}: {_mensagem_erro(resp)}")
        return resp

    def usuario_atual(self) -> Usuario:
        dados = self._get("/api/now/ui/user/current_user").json()["result"]
        if not dados.get("user_name") or dados["user_name"] == "guest":
            raise ServiceNowError("Sessão não autenticada")
        return Usuario(dados["user_sys_id"], dados["user_name"], dados.get("user_display_name") or dados["user_name"])

    def contar(self, tabela: str, query: str = "") -> int:
        resp = self._get(
            f"/api/now/table/{tabela}",
            {"sysparm_query": query, "sysparm_fields": "sys_id", "sysparm_limit": 1},
        )
        return int(resp.headers.get("X-Total-Count", "0"))


def _mensagem_erro(resp: requests.Response) -> str:
    try:
        erro = resp.json().get("error") or {}
        return erro.get("message") or erro.get("detail") or resp.reason
    except ValueError:
        return resp.reason
