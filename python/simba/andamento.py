"""Andamento do lote em execução, num arquivo JSON que o console lê (não é base de dados: só o lote atual).

O console também pede a parada criando o arquivo `parar` ao lado: o runner termina o caso em andamento (nunca
interrompe um Enviar) e encerra o lote.
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from simba import config


def arquivo() -> Path:
    return config.CONSOLE_DIR / "andamento.json"


def arquivo_parar() -> Path:
    return config.CONSOLE_DIR / "parar"


def pedir_parada() -> None:
    arquivo_parar().parent.mkdir(parents=True, exist_ok=True)
    arquivo_parar().touch()


def ler() -> Optional[dict]:
    try:
        return json.loads(arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Andamento:
    def __init__(self, total: int, simulacao: bool) -> None:
        self._lock = threading.Lock()
        self._inicio = time.monotonic()
        self.estado = {
            "pid": os.getpid(),
            "inicio": datetime.now().isoformat(timespec="seconds"),
            "fim": None,
            "situacao": "rodando",
            "simulacao": simulacao,
            "total": total,
            "atual": None,
            "casos": {},
        }
        arquivo_parar().unlink(missing_ok=True)
        self._gravar()

    def parada_pedida(self) -> bool:
        if arquivo_parar().exists():
            with self._lock:
                self.estado["situacao"] = "parando"
                self._gravar()
            return True
        return False

    def em_execucao(self, judtask: str, atendimento: str, etapa: str) -> None:
        with self._lock:
            self.estado["atual"] = {"judtask": judtask, "atendimento": atendimento, "etapa": etapa}
            self._gravar()

    def finalizado(self, judtask: str, situacao: str, mensagem: str = "", categoria: str = "") -> None:
        with self._lock:
            self.estado["casos"][judtask] = {
                "situacao": situacao,
                "categoria": categoria,
                "mensagem": mensagem,
                "fim": datetime.now().isoformat(timespec="seconds"),
            }
            if (self.estado["atual"] or {}).get("judtask") == judtask:
                self.estado["atual"] = None
            self._gravar()

    def encerrar(self, erro: str = "") -> None:
        with self._lock:
            self.estado["situacao"] = "erro" if erro else "encerrado"
            self.estado["erro"] = erro
            self.estado["atual"] = None
            self.estado["fim"] = datetime.now().isoformat(timespec="seconds")
            self._gravar()
        arquivo_parar().unlink(missing_ok=True)

    def _gravar(self) -> None:
        concluidos = len(self.estado["casos"])
        minutos = (time.monotonic() - self._inicio) / 60
        self.estado["concluidos"] = concluidos
        self.estado["por_minuto"] = round(concluidos / minutos, 2) if minutos > 0 else 0
        destino = arquivo()
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(".tmp")
        temporario.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")
        temporario.replace(destino)
