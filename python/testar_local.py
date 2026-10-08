r"""Executa o contrato do bot localmente sem reservar itens no ServiceNow.

Uso:
    .venv\Scripts\python testar_local.py

Para testar uma fila real, use ``--com-fila`` somente com as credenciais e o ambiente
do Simba configurados. Nesse modo, a execução pode alterar work items no ServiceNow.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from unittest.mock import patch


def _sdk_local() -> types.ModuleType:
    """Shim mínimo para validar o contrato quando o SDK interno não está instalado."""

    class LocalBot:
        @classmethod
        def from_runner(cls):
            return cls()

        def get_execution(self):
            return types.SimpleNamespace(
                parameters=os.environ.get("AUTOMIA_PARAMETERS", "{}")
            )

        def log(self, mensagem):
            print(f"[automia.log] {mensagem}")

        def error(self, erro, mensagem):
            print(f"[automia.error] {mensagem}: {erro}")

        def finish_task(self, status, mensagem, output=None):
            print(
                "[automia.finish_task] "
                + json.dumps(
                    {"status": status, "message": mensagem, "output": output},
                    ensure_ascii=False,
                )
            )

    return types.SimpleNamespace(
        Automia=LocalBot,
        TaskFinishStatus=types.SimpleNamespace(SUCCESS="success", FAILED="failed"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--com-fila",
        action="store_true",
        help="executa contra o ServiceNow; sem esta opção, apenas valida o contrato do bot",
    )
    args = parser.parse_args()

    os.environ.setdefault("AUTOMIA_EXECUTION_ID", "teste-local")
    os.environ.setdefault("AUTOMIA_TASK_ID", "teste-local")
    os.environ.setdefault("AUTOMIA_PARAMETERS", json.dumps({"filas": ["validador"]}))

    try:
        import automia
    except ImportError:
        if args.com_fila:
            raise SystemExit(
                "SDK Automia não instalado. Instale-o pelo feed interno da XP antes de usar --com-fila."
            )
        automia = _sdk_local()
        sys.modules["automia"] = automia
    else:
        automia.Automia.RAISE_NOT_CONNECTED = False

    import bot

    if args.com_fila:
        bot.main()
        return

    with patch("bot.executar_uma_vez", return_value={"status": "empty", "queue": None}):
        bot.main()


if __name__ == "__main__":
    main()
