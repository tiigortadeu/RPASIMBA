"""Testa conectividade e autenticação no ServiceNow com uma requisição somente leitura.

Exemplo no CMD:

    set SN_INSTANCIA=minha-instancia
    set SN_USUARIO=usuario_de_integracao
    set SN_SENHA=senha
    python testar_servicenow.py

O script não cria, altera, exclui registros nem envia anexos.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from simba.servicenow import normalizar_instancia


ENDPOINT_PADRAO = "/api/now/table/x_xpi_ofj_judicial_office_task?sysparm_limit=1"


def montar_url(instancia: str, endpoint: str) -> str:
    caminho = endpoint.strip()
    if not caminho.startswith("/"):
        caminho = f"/{caminho}"
    return f"{normalizar_instancia(instancia)}{caminho}"


def resumir_json(corpo: object) -> str:
    if isinstance(corpo, dict):
        resultado = corpo.get("result")
        if isinstance(resultado, list):
            return f"JSON válido; result contém {len(resultado)} registro(s)."
        if isinstance(resultado, dict):
            return "JSON válido; result contém um registro."
    return "JSON válido; formato recebido diferente do esperado."


def executar(instancia: str, usuario: str, senha: str, endpoint: str, timeout: float) -> int:
    if not usuario.strip():
        print("ERRO: informe SN_USUARIO.", file=sys.stderr)
        return 2
    if not senha:
        print("ERRO: informe SN_SENHA.", file=sys.stderr)
        return 2

    try:
        url = montar_url(instancia, endpoint)
    except ValueError as erro:
        print(f"ERRO DE CONFIGURAÇÃO: {erro}", file=sys.stderr)
        return 2

    print(f"GET {url}")
    try:
        resposta = requests.get(
            url,
            auth=(usuario, senha),
            headers={"Accept": "application/json"},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as erro:
        print(f"ERRO DE CONEXÃO: {erro}", file=sys.stderr)
        return 3

    print(f"HTTP {resposta.status_code}")
    if resposta.is_redirect:
        print(
            "ERRO: a instância redirecionou a requisição; verifique a URL e as credenciais.",
            file=sys.stderr,
        )
        return 4
    if resposta.status_code in (401, 403):
        print("ERRO: acesso negado; verifique usuário, senha e permissões.", file=sys.stderr)
        return 4
    if not 200 <= resposta.status_code < 300:
        detalhe = resposta.text[:500].replace("\r", " ").replace("\n", " ")
        print(f"ERRO HTTP: {detalhe}", file=sys.stderr)
        return 4

    try:
        corpo = resposta.json()
    except json.JSONDecodeError:
        print("ERRO: a resposta HTTP 2xx não contém JSON válido.", file=sys.stderr)
        return 5

    print(resumir_json(corpo))
    print("TESTE ServiceNow OK: somente leitura.")
    return 0


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instancia", default=os.getenv("SN_INSTANCIA", ""))
    parser.add_argument("--usuario", default=os.getenv("SN_USUARIO", ""))
    parser.add_argument("--senha", default=os.getenv("SN_SENHA", ""))
    parser.add_argument("--endpoint", default=ENDPOINT_PADRAO)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    return executar(args.instancia, args.usuario, args.senha, args.endpoint, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
