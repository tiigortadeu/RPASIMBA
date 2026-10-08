import os
import socket
from pathlib import Path

from dotenv import load_dotenv
from win32com.shell import shell, shellcon

# Configuração e segredos de cada runner (python/.env, fora do git); variáveis já definidas têm prioridade.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _documents_dir() -> Path:
    # Resolve a pasta Documentos real (cobre o redirecionamento do OneDrive).
    return Path(shell.SHGetKnownFolderPath(shellcon.FOLDERID_Documents))


SIMBA_HOME = Path(os.environ.get("SIMBA_HOME", _documents_dir() / "Programas SIMBA"))
SIMBA_EXE = SIMBA_HOME / "Validador" / "simba-validador.exe"
TRANSMISSOR_EXE = SIMBA_HOME / "Transmissor" / "simba-transmissor.exe"
# Por atendimento transmitido: comprovante de envio e zip com os arquivos validados (pode ser uma pasta de rede).
TRANSMITIDOS = Path(os.environ.get("SIMBA_TRANSMITIDOS", SIMBA_HOME / "Transmitidos"))
# Atendimentos já processados saem do dadosValidador para cá, para as listas do Simba não crescerem.
ARQUIVO_DIR = Path(os.environ.get("SIMBA_ARQUIVO", SIMBA_HOME / "Arquivo"))
# Transmite logo depois da validação, no mesmo work item e com o pacote gerado nesta máquina, sem esperar a
# tarefa/fila do Transmissor. A chave vem do CNPJ do caso: SIMBA_CHAVE_<CNPJ só dígitos>=<arquivo de chaves>.
TRANSMITIR_APOS_VALIDAR = os.environ.get("SIMBA_TRANSMITIR_APOS_VALIDAR", "1") == "1"
# Arquivos de chaves do Transmissor, um por instituição; a senha de cada um fica em SIMBA_SENHA_<NOME DA CHAVE>.
CHAVES_DIR = Path(os.environ.get("SIMBA_CHAVES_DIR", SIMBA_HOME / "Chaves"))

# --- Runner (filas do RPA Hub no ServiceNow) ---
SN_INSTANCIA = os.environ.get("SN_INSTANCIA", "")
SN_USUARIO = os.environ.get("SN_USUARIO", "")
SN_SENHA = os.environ.get("SN_SENHA", "")
# Identifica o runner nos work items (remarks); um por sessão Windows.
RUNNER_ID = os.environ.get("RUNNER_ID", f"{socket.gethostname()}-{os.environ.get('USERNAME', '')}")
# Arquivos baixados por work item; limpo ao terminar cada item.
TRABALHO_DIR = Path(os.environ.get("SIMBA_TRABALHO", SIMBA_HOME / "Trabalho"))
# Espera entre reservar um item e conferir que a reserva é minha (outro runner pode ter gravado por cima).
RESERVA_VERIFICACAO = 2
HEARTBEAT = 60
# Item em andamento sem heartbeat por mais que isso é considerado abandonado (runner caiu).
LEASE = 15 * 60
REAPER_INTERVALO = 5 * 60
MAX_TENTATIVAS = 3
# Espera sem itens na fila antes de consultar de novo.
FILA_VAZIA_ESPERA = 30

JAB_DLL = os.environ.get("RC_JAVA_ACCESS_BRIDGE_DLL", r"C:\Windows\System32\WindowsAccessBridge-64.dll")

POLL_INTERVAL = 0.1
# A abertura leva ~1,5s, mas às vezes a JVM do Simba trava 15-30s+ antes da primeira chamada ao servidor.
STARTUP_TIMEOUT = 60
SCREEN_TIMEOUT = 20
# Verificação de arquivos grandes (o Simba mostra ~2500 linhas/s).
VALIDACAO_TIMEOUT = 300
# Upload do pacote ao órgão.
ENVIO_TIMEOUT = 300
STEP_RETRIES = 2
