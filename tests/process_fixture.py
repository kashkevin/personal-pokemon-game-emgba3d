"""Direct stdlib-only Python child for process-lifetime/crash tests.

The Windows venv executable redirects to a second process. Killing that launcher
does not kill the interpreter holding our file lock. These children need only
the stdlib and project PYTHONPATH, so launch the actual interpreter directly.
"""
from pathlib import Path
import sys


def direct_python():
    executable = sys._base_executable if sys.platform == "win32" else sys.executable
    if not Path(executable).is_file():
        raise RuntimeError("process fixture needs the actual Python interpreter")
    return executable
