import os
from pathlib import Path

from win32com.shell import shell, shellcon


def _documents_dir() -> Path:
    # Resolve a pasta Documentos real (cobre o redirecionamento do OneDrive).
    return Path(shell.SHGetKnownFolderPath(shellcon.FOLDERID_Documents))


SIMBA_HOME = Path(os.environ.get("SIMBA_HOME", _documents_dir() / "Programas SIMBA"))
SIMBA_EXE = SIMBA_HOME / "Validador" / "simba-validador.exe"

JAB_DLL = os.environ.get("RC_JAVA_ACCESS_BRIDGE_DLL", r"C:\Windows\System32\WindowsAccessBridge-64.dll")

POLL_INTERVAL = 0.1
STARTUP_TIMEOUT = 30
SCREEN_TIMEOUT = 20
# Verificação de arquivos grandes (o Simba mostra ~2500 linhas/s).
VALIDACAO_TIMEOUT = 300
STEP_RETRIES = 2
