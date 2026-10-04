"""Login SSO numa janela de navegador embutida; reaproveita a sessão para a API REST."""
import logging
from typing import Optional
from urllib.parse import urlparse

from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from simba.servicenow import ServiceNow, ServiceNowError

log = logging.getLogger(__name__)

PAGINAS_DE_LOGIN = ("/login.do", "/login_with_sso.do", "/logout.do", "/external_logout_complete.do")
# Página clássica leve, que sempre define g_ck, para quando a página inicial não expõe o token.
PAGINA_TOKEN = "/sys_user_list.do?sysparm_query=sys_idISEMPTY"
JS_TOKEN = """
(function () {
    if (window.g_ck) return window.g_ck;
    var f = document.querySelector('iframe#gsft_main');
    try { if (f && f.contentWindow.g_ck) return f.contentWindow.g_ck; } catch (e) {}
    return '';
})()
"""


class LoginSSO(QDialog):
    def __init__(self, instancia: str, parent=None) -> None:
        super().__init__(parent)
        self.instancia = instancia
        self.host = urlparse(instancia).hostname
        self.cliente: Optional[ServiceNow] = None
        self._cookies: dict[str, str] = {}
        self._buscou_pagina_token = False

        self.setWindowTitle(f"Login — {self.host}")
        self.resize(1000, 750)

        # Perfil sem disco: a sessão some ao fechar o app. Sem parent Qt, para ser liberado depois da página.
        self.profile = QWebEngineProfile()
        self.profile.cookieStore().cookieAdded.connect(self._cookie_adicionado)
        self.profile.cookieStore().cookieRemoved.connect(self._cookie_removido)
        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(self.profile, self.view))
        self.view.loadFinished.connect(self._pagina_carregada)

        self.status = QLabel("Faça o login na janela abaixo.")
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.view)

        # A raiz segue o redirecionamento configurado na instância (Microsoft). /login_with_sso.do sem
        # glide_sso_id usa o IdP padrão, que pode ser o SSOCircle de exemplo (erro H0D0C).
        self.view.load(QUrl(instancia + "/"))

    def _da_instancia(self, cookie: QNetworkCookie) -> bool:
        dominio = cookie.domain().lstrip(".")
        return self.host == dominio or self.host.endswith("." + dominio)

    def _cookie_adicionado(self, cookie: QNetworkCookie) -> None:
        if self._da_instancia(cookie):
            self._cookies[bytes(cookie.name()).decode()] = bytes(cookie.value()).decode()

    def _cookie_removido(self, cookie: QNetworkCookie) -> None:
        if self._da_instancia(cookie):
            self._cookies.pop(bytes(cookie.name()).decode(), None)

    def _pagina_carregada(self, ok: bool) -> None:
        url = self.view.url()
        # Só host e caminho: a query do IdP pode carregar tokens.
        log.info("Página carregada (ok=%s): %s%s", ok, url.host(), url.path())
        if not ok or url.host() != self.host:
            return
        self.view.page().runJavaScript(JS_TOKEN, 0, lambda token: self._token_lido(token, url.path()))

    def _token_lido(self, token: str, path: str) -> None:
        if token:
            cliente = ServiceNow.por_sessao(self.instancia, dict(self._cookies), token)
            try:
                usuario = cliente.usuario_atual()
            except ServiceNowError as err:
                # Na tela de login o g_ck é da sessão guest; espera o login terminar.
                log.info("Sessão ainda não autenticada: %s", err)
                return
            log.info("Login SSO concluído como %s", usuario.user_name)
            self.cliente = cliente
            self.accept()
            return
        if path not in PAGINAS_DE_LOGIN and not self._buscou_pagina_token:
            self._buscou_pagina_token = True
            self.status.setText("Login concluído; obtendo o token da sessão...")
            self.view.load(QUrl(self.instancia + PAGINA_TOKEN))
