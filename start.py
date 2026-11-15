"""Lanzador del SMC Notebook Bot para Railway.

Funciona en los dos casos:
  1) el repo tiene la carpeta `smcbot/` (estructura correcta), o
  2) los .py quedaron sueltos en la raiz del repo (pasa al subir archivos a GitHub
     desde la web y se pierde la carpeta). Es el caso del error
     "ImportError: attempted relative import with no known parent package".

Uso:  python start.py
"""
import importlib.util
import os
import runpy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = "smcbot"
SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules", ".railway"}


def _log(msg: str) -> None:
    print(f"[start] {msg}", flush=True)


def _tree(limit: int = 80) -> str:
    """Lista la raiz del repo y un nivel de subcarpetas (para diagnosticar desde los logs)."""
    lines = []
    for entry in sorted(os.scandir(ROOT), key=lambda e: e.name):
        if entry.name in SKIP:
            continue
        lines.append("  " + entry.name + ("/" if entry.is_dir() else ""))
        if entry.is_dir():
            for sub in sorted(os.scandir(entry.path), key=lambda e: e.name):
                if sub.name not in SKIP:
                    lines.append("    " + sub.name + ("/" if sub.is_dir() else ""))
        if len(lines) >= limit:
            lines.append("  ...")
            break
    return "\n".join(lines)


def _prepare_package() -> str:
    """Deja `smcbot` importable. Devuelve la estructura detectada ('' si no hay bot)."""
    if (ROOT / PKG / "main.py").is_file():
        sys.path.insert(0, str(ROOT))
        return "carpeta smcbot/"

    if (ROOT / "main.py").is_file():
        # .py sueltos en la raiz: se registra la propia raiz como paquete `smcbot`
        # para que funcionen los imports relativos (from . import __version__, from .config ...).
        init = ROOT / "__init__.py"
        if init.is_file():
            spec = importlib.util.spec_from_file_location(
                PKG, init, submodule_search_locations=[str(ROOT)]
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[PKG] = module
            spec.loader.exec_module(module)
        else:
            _log("AVISO: falta __init__.py en la raiz; uso un paquete vacio (version desconocida).")
            module = types.ModuleType(PKG)
            module.__path__ = [str(ROOT)]
            module.__version__ = "desconocida"
            sys.modules[PKG] = module
        return "archivos sueltos en la raiz del repo"

    return ""


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    _log(f"Python {sys.version.split()[0]} | carpeta {ROOT}")
    layout = _prepare_package()
    if not layout:
        _log("ERROR: no encuentro main.py ni smcbot/main.py. Contenido del repo:")
        print(_tree(), flush=True)
        sys.exit(1)
    _log(f"Estructura detectada: {layout}")
    runpy.run_module(f"{PKG}.main", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
