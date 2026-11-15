"""Mutantes R-08 (SPEC-127): cada mutante rompe la guarda de fechas y la suite
debe fallar. Trabaja sobre una copia temporal; no toca el repo ni Odoo.

Uso: python scripts/mutantes_r08.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ["tests/test_deadline_law.py", "tests/test_task_write_contract.py"]

SCH = "app/schemas.py"
TSK = "app/tools/tasks.py"
DSP = "app/tools/openai_write_dispatch.py"

GUARD = '''    if "date_deadline" in normalized:
        pre = await odoo.read(actor, "project.task", [task_id], ["id", "date_deadline"])
        if not pre:
            raise PermissionError(f"task_not_accessible:{task_id}")
        ensure_deadline_not_moved(task_id, pre[0].get("date_deadline"))
'''
POLICY = '    _ensure_policy(policy, actor, "odoo_update_task_apl", "project.task", "write")\n'
WRITE = '    await odoo.write(actor, "project.task", [task_id], normalized)\n'
POINTER = "usa ley_fechas.py o la herramienta de reprogramar con nota."

MUTANTES = [
    ("M-R08-01 sin llamada a la guarda", TSK,
     '        ensure_deadline_not_moved(task_id, pre[0].get("date_deadline"))\n',
     '        pass\n'),
    ("M-R08-02 mira changes, no normalized", TSK,
     'if "date_deadline" in normalized:', 'if "date_deadline" in changes:'),
    ("M-R08-03 la guarda no lanza nunca", SCH,
     "    if current_deadline:\n        raise", "    if False:\n        raise"),
    ("M-R08-04 la guarda lanza siempre", SCH,
     "    if current_deadline:\n        raise", "    if True:\n        raise"),
    ("M-R08-05 guarda despues del write", TSK,
     GUARD + "\n", "\n"),  # se reinserta tras el write mas abajo (ver aplicar)
    ("M-R08-06 fallo abierto si no se lee", TSK,
     '        if not pre:\n            raise PermissionError(f"task_not_accessible:{task_id}")\n'
     '        ensure_deadline_not_moved(task_id, pre[0].get("date_deadline"))\n',
     '        if pre:\n            ensure_deadline_not_moved(task_id, pre[0].get("date_deadline"))\n'),
    ("M-R08-07 hereda de ValidationError", SCH,
     "class DeadlineLockedError(PermissionError):", "class DeadlineLockedError(ValidationError):"),
    ("M-R08-08 sin except propio en el despacho", DSP,
     '    except DeadlineLockedError as exc:\n        return _action_error(str(exc), kind="error:deadline_locked")\n',
     ''),
    ("M-R08-09 el literal pierde el puntero", SCH,
     "usa ley_fechas.py o la herramienta de reprogramar con nota.", "usa otra via."),
    ("M-R08-10 compara y deja pasar la misma fecha", TSK,
     '        ensure_deadline_not_moved(task_id, pre[0].get("date_deadline"))\n',
     '        if str(pre[0].get("date_deadline") or "")[:10] != str(normalized["date_deadline"]):\n'
     '            ensure_deadline_not_moved(task_id, pre[0].get("date_deadline"))\n'),
    ("M-R08-11 lectura previa antes de la politica", TSK,
     POLICY + "\n" + GUARD, "\n" + GUARD + POLICY),
]


def pytest_rc(work: Path) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", *TESTS],
                       cwd=work, capture_output=True, text=True)
    return r.returncode


def fresh_copy() -> Path:
    work = Path(tempfile.mkdtemp(prefix="mut_r08_"))
    for d in ("app", "tests", "config"):
        shutil.copytree(ROOT / d, work / d, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "pyproject.toml", work / "pyproject.toml")
    return work


def aplicar(work: Path, nombre: str, fichero: str, a: str, b: str) -> None:
    p = work / fichero
    orig = p.read_text(encoding="utf-8")
    assert orig.count(a) == 1, f"{nombre}: cadena no unica o ausente"
    nuevo = orig.replace(a, b)
    if nombre.startswith("M-R08-05"):
        # la guarda se mueve despues del write
        nuevo = nuevo.replace(WRITE, WRITE + GUARD)
        assert nuevo.count(GUARD) == 1
    p.write_text(nuevo, encoding="utf-8")


def main() -> int:
    work = fresh_copy()
    try:
        if pytest_rc(work) != 0:
            print("FALLA original")
            return 1
        print("ok original")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    vivos = 0
    for nombre, fichero, a, b in MUTANTES:
        work = fresh_copy()
        try:
            aplicar(work, nombre, fichero, a, b)
            if pytest_rc(work) != 0:
                print(f"muere {nombre}")
            else:
                print(f"VIVE  {nombre}")
                vivos += 1
        finally:
            shutil.rmtree(work, ignore_errors=True)
    ok = vivos == 0
    print("RESULTADO=OK" if ok else f"RESULTADO=FALLA ({vivos} vivos)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
