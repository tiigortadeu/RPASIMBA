"""Entrypoint single-entrypoint do bot Simba para o Automia."""

from __future__ import annotations

import json
from typing import Any

from automia import Automia, TaskFinishStatus

from simba.runner import executar_uma_vez


def _parametros(execution: Any) -> dict[str, Any]:
    """Normaliza parâmetros do Automia e rejeita formatos ambíguos."""
    parametros = getattr(execution, "parameters", None)
    if parametros is None:
        return {}
    if isinstance(parametros, str):
        try:
            parametros = json.loads(parametros)
        except json.JSONDecodeError as exc:
            raise ValueError("execution.parameters deve ser um objeto JSON válido") from exc
    if not isinstance(parametros, dict):
        raise ValueError("execution.parameters deve ser um objeto")
    return parametros


def _filas(parametros: dict[str, Any]) -> list[str]:
    valor = parametros.get("filas")
    if valor is None:
        return ["validador"]
    if isinstance(valor, str):
        filas = [item.strip() for item in valor.split(",") if item.strip()]
    elif isinstance(valor, list) and all(isinstance(item, str) for item in valor):
        filas = [item.strip() for item in valor if item.strip()]
    else:
        raise ValueError("o parâmetro 'filas' deve ser uma string ou uma lista de strings")
    if not filas:
        raise ValueError("o parâmetro 'filas' não pode ser vazio")
    return filas


def _max_itens(parametros: dict[str, Any]) -> int:
    """Itens por execução (padrão 1). Com mais de um, a fila do Validador roda em esteira sem reabrir o Simba."""
    valor = parametros.get("max_itens", 1)
    if isinstance(valor, str) and valor.strip().isdigit():
        valor = int(valor)
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise ValueError("o parâmetro 'max_itens' deve ser um inteiro maior ou igual a 1")
    return valor


def main() -> None:
    bot = Automia.from_runner()
    execution = bot.get_execution()

    try:
        parametros = _parametros(execution)
        resultado = executar_uma_vez(_filas(parametros), _max_itens(parametros))
        if resultado["status"] == "empty":
            mensagem = "Nenhum item disponível nas filas configuradas."
        elif "itens" in resultado:
            mensagem = f"{resultado['itens']} item(ns) processado(s) na fila {resultado['queue']}."
        else:
            mensagem = f"Item processado na fila {resultado['queue']}."
        bot.log(mensagem)
        bot.finish_task(TaskFinishStatus.SUCCESS, mensagem, output=resultado)
    except Exception as erro:
        bot.error(erro, "Falha durante a execução do bot Simba")
        bot.finish_task(TaskFinishStatus.FAILED, str(erro))


if __name__ == "__main__":
    main()
