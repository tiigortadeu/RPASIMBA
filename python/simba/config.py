import os
import socket
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from win32com.shell import shell, shellcon

# Configuração e segredos de cada runner (.env na raiz do projeto, fora do git); variáveis já definidas têm prioridade.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _documents_dir() -> Path:
    # Resolve a pasta Documentos real (cobre o redirecionamento do OneDrive).
    return Path(shell.SHGetKnownFolderPath(shellcon.FOLDERID_Documents))


def _caminho(variavel: str, padrao: Path) -> Path:
    # Variável vazia no .env (ex.: "SIMBA_HOME=") vale como não definida.
    return Path(os.environ.get(variavel) or padrao)


SIMBA_HOME = _caminho("SIMBA_HOME", _documents_dir() / "Programas SIMBA")
SIMBA_VALIDADOR_HOME = _caminho("SIMBA_VALIDADOR_HOME", SIMBA_HOME / "Validador")
SIMBA_TRANSMISSOR_HOME = _caminho("SIMBA_TRANSMISSOR_HOME", SIMBA_HOME / "Transmissor")
SIMBA_EXE = _caminho("SIMBA_VALIDADOR_EXE", SIMBA_VALIDADOR_HOME / "simba-validador.exe")
TRANSMISSOR_EXE = _caminho("SIMBA_TRANSMISSOR_EXE", SIMBA_TRANSMISSOR_HOME / "simba-transmissor.exe")
# O Simba grava o dadosValidador um nível acima da pasta do .exe: com Validador e Transmissor lado a lado em
# <SIMBA_HOME> a pasta é a mesma; com versões em subpastas (Validador\5.8.7) cada programa tem a sua.
SIMBA_VALIDADOR_DADOS = _caminho("SIMBA_VALIDADOR_DADOS", SIMBA_EXE.parent.parent / "dadosValidador")
SIMBA_TRANSMISSOR_DADOS = _caminho("SIMBA_TRANSMISSOR_DADOS", TRANSMISSOR_EXE.parent.parent / "dadosValidador")
# Por atendimento transmitido: comprovante de envio e zip com os arquivos validados (pode ser uma pasta de rede).
TRANSMITIDOS = _caminho("SIMBA_TRANSMITIDOS", SIMBA_HOME / "Transmitidos")
# Atendimentos já processados saem do dadosValidador para cá, para as listas do Simba não crescerem.
ARQUIVO_DIR = _caminho("SIMBA_ARQUIVO", SIMBA_HOME / "Arquivo")
# Transmite logo depois da validação, no mesmo work item e com o pacote gerado nesta máquina, sem esperar a
# tarefa/fila do Transmissor. A chave vem do órgão de destino (prefixo do atendimento), pelo CSV de chaves.
TRANSMITIR_APOS_VALIDAR = os.environ.get("SIMBA_TRANSMITIR_APOS_VALIDAR", "1") == "1"
# Arquivos .ASB do Transmissor (um por órgão de destino) e o CSV com nome da chave, senha e responsável.
CHAVES_DIR = _caminho("SIMBA_CHAVES_DIR", SIMBA_HOME / "Chaves")
CHAVES_CSV = _caminho("SIMBA_CHAVES_CSV", CHAVES_DIR / "chaves.csv")

# --- Runner (filas do RPA Hub no ServiceNow) ---
# Só work items criados a partir desta data (AAAA-MM-DD) são reservados, recolhidos pelo reaper e mostrados no
# console: os itens antigos das filas ficam parados. Vazio: todos.
ITENS_DESDE = os.environ.get("SIMBA_ITENS_DESDE", "").strip()
if ITENS_DESDE:
    datetime.strptime(ITENS_DESDE, "%Y-%m-%d")  # falha logo na partida com data inválida no .env
SN_INSTANCIA = os.environ.get("SN_INSTANCIA", "")
SN_USUARIO = os.environ.get("SN_USUARIO", "")
SN_SENHA = os.environ.get("SN_SENHA", "")
# Limite do usuário de integração: bloqueio acima de 100/min. Valor por processo (runner).
SN_REQUISICOES_POR_MINUTO = float(os.environ.get("SN_REQUISICOES_POR_MINUTO") or 50)
# Identifica o runner nos work items (remarks); um por sessão Windows.
RUNNER_ID = os.environ.get("RUNNER_ID", f"{socket.gethostname()}-{os.environ.get('USERNAME', '')}")
# Arquivos baixados por work item; limpo ao terminar cada item.
TRABALHO_DIR = _caminho("SIMBA_TRABALHO", SIMBA_HOME / "Trabalho")
LOGS_DIR = _caminho("SIMBA_LOGS", SIMBA_HOME / "logs")
# Console: retrato baixado do SN, planilha de escopo, andamento do lote e exportações.
CONSOLE_DIR = _caminho("SIMBA_CONSOLE", SIMBA_HOME / "Console")
# Lista do Bacen (fonte da verdade do que precisa ser respondido): aba "3290", uma linha por requisição do CCS.
LISTA_BACEN = _caminho("SIMBA_LISTA_BACEN", CONSOLE_DIR / "lista_bacen.xlsx")
# Endereço do console: só a própria VM por padrão (o console dispara execuções reais e não tem login).
CONSOLE_HOST = os.environ.get("CONSOLE_HOST") or "127.0.0.1"

# Executável da Cabine CCS-JUD (ex.: compartilhamento de rede); só os scripts cabine_* usam.
CABINE_EXE = Path(os.environ["CABINE_EXE"]) if os.environ.get("CABINE_EXE") else None

HEARTBEAT = 60
# Item em andamento sem heartbeat por mais que isso é considerado abandonado (runner caiu).
LEASE = 15 * 60
REAPER_INTERVALO = 5 * 60
MAX_TENTATIVAS = 3
# Espera sem itens na fila antes de consultar de novo.
FILA_VAZIA_ESPERA = 30
# Falhas seguidas do SN ao reservar antes de a esteira parar (com FILA_VAZIA_ESPERA entre elas: ~10 min).
RESERVA_TENTATIVAS = 20

JAB_DLL = os.environ.get("RC_JAVA_ACCESS_BRIDGE_DLL") or r"C:\Windows\System32\WindowsAccessBridge-64.dll"
# Opções passadas à JVM do Simba ao abri-lo: o mapeamento das telas é em português.
SIMBA_JAVA_OPCOES = os.environ.get("SIMBA_JAVA_OPCOES") or "-Duser.language=pt -Duser.country=BR"

POLL_INTERVAL = 0.1
# A abertura leva ~1,5s, mas às vezes a JVM do Simba trava 15-30s+ antes da primeira chamada ao servidor.
STARTUP_TIMEOUT = 60
SCREEN_TIMEOUT = 20
# Verificação de arquivos grandes (o Simba mostra ~2500 linhas/s).
VALIDACAO_TIMEOUT = 300
# Upload do pacote ao órgão.
ENVIO_TIMEOUT = 300
STEP_RETRIES = 2
# Espera o programa sair pelo WM_CLOSE antes de matar o processo.
FECHAR_TIMEOUT = 5
# O Validador fica aberto entre os casos; a cada N casos é reiniciado e os casos acumulados são arquivados.
VALIDADOR_REINICIO = 25
