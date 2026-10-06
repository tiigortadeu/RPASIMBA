"""Casos fictícios em lote, com números e DVs diferentes, para testar o Simba com muitos atendimentos."""
import json
from pathlib import Path

from simba.cadastro import Caso

BASE = Path(__file__).parent / "data" / "caso_teste.json"


def dv_atendimento(orgao: str, caso: str) -> str:
    """DV do Simba (Util.getDvAtendimento): dois dígitos módulo 11, como no CPF, sobre órgão + caso.

    Confere com os casos conhecidos: 002 + 013110 -> 03 e 001 + 006638 -> 18.
    """
    digitos = [int(c) for c in orgao + caso]
    for _ in range(2):
        peso = len(digitos) + 1
        resto = sum(d * (peso - i) for i, d in enumerate(digitos)) % 11
        digitos.append(0 if resto < 2 else 11 - resto)
    return f"{digitos[-2]}{digitos[-1]}"


def caso_ficticio(numero: int) -> Caso:
    """Variação do caso de teste: número `numero`, DV calculado e 1 ou 2 investigados (PF, ou PF + PJ)."""
    dados = json.loads(BASE.read_text(encoding="utf-8"))
    dados["Caso"] = f"{numero:06d}"
    dados["DV"] = dv_atendimento(dados["Destino"].split("-")[0], dados["Caso"])
    dados["Investigados"] = dados["Investigados"][: 1 + numero % 2]
    return Caso.from_json(dados)
