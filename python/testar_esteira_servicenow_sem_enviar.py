r"""Roda o runner em esteira com itens reais da fila do ServiceNow, sem gravar nada no ServiceNow e sem enviar.

Leituras (fila, JUDTASK, anexos, GABs) vão para a instância do .env, no limite SN_REQUISICOES_POR_MINUTO.
Gravações (reserva, etapa, anexos de saída, comprovante, conclusão) ficam só em memória, mas contam no limite
como se fossem feitas, para medir o ritmo real. Leituras seguintes do mesmo registro enxergam essas gravações.
O Validador roda de verdade; o Transmissor seleciona o atendimento, mas carregar a chave e o Enviar são
simulados (nunca há clique em Enviar). Comprovantes simulados e casos arquivados vão para uma pasta de teste.

Uso:
    .venv\Scripts\python testar_esteira_servicenow_sem_enviar.py --limite 30
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter

from simba import config, simulacao
from simba.fila import TABELA
from simba.runner import Runner


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limite", type=int, default=30, help="quantidade máxima de itens pendentes")
    args = parser.parse_args()
    if not (config.SN_INSTANCIA and config.SN_USUARIO and config.SN_SENHA):
        parser.error("defina SN_INSTANCIA, SN_USUARIO e SN_SENHA no .env")

    sn, pasta_teste = simulacao.ativar(Runner)
    runner = Runner(sn, ["validador"])
    # O reaper devolveria os itens presos de outros robôs; neste teste ele não roda.
    runner._ultimo_reaper = time.monotonic()
    print(f"Instância: {sn.instancia} | limite {config.SN_REQUISICOES_POR_MINUTO:.0f} req/min | pasta {pasta_teste}")
    print("Somente leitura: nenhuma gravação chega ao ServiceNow; Enviar simulado.", flush=True)

    inicio = time.monotonic()
    resumo = runner.processar_lote(args.limite)
    total = time.monotonic() - inicio

    itens = {sys_id: v for (tabela, sys_id), v in sn.gravado.items() if tabela == TABELA}
    status = Counter(v.get("status", "?") for v in itens.values())
    print(f"\nRESUMO: {resumo} em {total:.0f}s")
    print(f"Status simulados dos work items: {dict(status)}")
    for sys_id, v in itens.items():
        if v.get("status") != "success":
            print(f"  {v.get('status')} {sys_id}: {v.get('response_content', '')[:300]}")
    n = resumo["itens"] or 1
    req = sum(sn.requisicoes.values())
    print(f"Requisições: {req} ({req / n:.1f} por item; {req / total * 60:.0f}/min) {dict(sn.requisicoes)}")
    print(f"Ritmo: {resumo['itens'] / total * 60:.1f} itens/min -> 10 mil em {10000 / max(resumo['itens'] / total * 60, 0.01) / 60:.1f} h")
    (pasta_teste / "resultado.json").write_text(
        json.dumps({"resumo": resumo, "itens": itens, "requisicoes": sn.requisicoes}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
