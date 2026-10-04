"""App desktop: conexão com o ServiceNow (SSO pela janela de login ou basic auth)."""
import logging
import sys
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from simba.servicenow import TABELA_TAREFAS, ServiceNow, ServiceNowError, normalizar_instancia
from simba.ui.sso import LoginSSO

log = logging.getLogger(__name__)


class JanelaPrincipal(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.cliente: Optional[ServiceNow] = None
        self.setWindowTitle("RPA Simba — ServiceNow")
        self.resize(520, 360)

        self.instancia = QLineEdit()
        self.instancia.setPlaceholderText("empresa.service-now.com")

        botao_sso = QPushButton("Entrar com SSO")
        botao_sso.clicked.connect(self.entrar_sso)

        self.usuario = QLineEdit()
        self.senha = QLineEdit()
        self.senha.setEchoMode(QLineEdit.Password)
        botao_basic = QPushButton("Entrar com usuário e senha")
        botao_basic.clicked.connect(self.entrar_basic)
        grupo_basic = QGroupBox("Basic auth (usuário com senha local)")
        form_basic = QFormLayout(grupo_basic)
        form_basic.addRow("Usuário", self.usuario)
        form_basic.addRow("Senha", self.senha)
        form_basic.addRow(botao_basic)

        self.status = QLabel("Desconectado.")
        self.status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Instância", self.instancia)
        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(botao_sso)
        layout.addWidget(grupo_basic)
        layout.addWidget(self.status)
        layout.addStretch()
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

    def _instancia(self) -> Optional[str]:
        try:
            return normalizar_instancia(self.instancia.text())
        except ValueError as err:
            self.status.setText(str(err))
            return None

    def entrar_sso(self) -> None:
        instancia = self._instancia()
        if not instancia:
            return
        login = LoginSSO(instancia, self)
        if login.exec() and login.cliente:
            self.conectado(login.cliente)
        else:
            self.status.setText("Login SSO cancelado.")

    def entrar_basic(self) -> None:
        instancia = self._instancia()
        if not instancia:
            return
        cliente = ServiceNow.por_basic_auth(instancia, self.usuario.text().strip(), self.senha.text())
        self.senha.clear()
        self.conectado(cliente)

    def conectado(self, cliente: ServiceNow) -> None:
        try:
            usuario = cliente.usuario_atual()
        except ServiceNowError as err:
            self.status.setText(f"Falha ao conectar: {err}")
            return
        self.cliente = cliente
        linhas = [f"Conectado em {cliente.instancia} como {usuario.nome} ({usuario.user_name})."]
        try:
            total = cliente.contar(TABELA_TAREFAS)
            linhas.append(f"Tabela {TABELA_TAREFAS}: {total} registro(s) visíveis.")
        except ServiceNowError as err:
            linhas.append(f"Sem acesso à tabela {TABELA_TAREFAS}: {err}")
        self.status.setText("\n".join(linhas))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    janela = JanelaPrincipal()
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
