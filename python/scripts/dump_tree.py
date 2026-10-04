"""Despeja a árvore JAB de todas as janelas Java abertas, com o caminho no formato do .iBot.

Uso: python scripts/dump_tree.py [filtro-de-titulo]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simba.jab import Bridge, wait_for  # noqa: E402


def main() -> None:
    title_filter = sys.argv[1] if len(sys.argv) > 1 else ""
    bridge = Bridge.get()
    # O bridge descobre as JVMs de forma assíncrona após iniciar.
    windows = wait_for(bridge.windows, timeout=5, what="janelas Java")
    for w in windows:
        if title_filter not in w.title:
            continue
        print(f"\n### janela {w.title!r} pid={w.pid} hwnd={w.hwnd}")
        root = bridge.window(w.title, {w.pid})
        paths = {0: ""}
        for depth, element in root.walk():
            if depth > 0:
                segment = f"{element.role}[{element.info.indexInParent}]"
                paths[depth] = f"{paths[depth - 1]}.{segment}" if depth > 1 else segment
            print(
                f"{'  ' * depth}{element.role} name={element.name!r} states={element.states!r} "
                f"path={paths[depth]!r}"
            )


if __name__ == "__main__":
    main()
