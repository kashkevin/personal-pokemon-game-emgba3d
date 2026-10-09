"""pytest bootstrap: make src/ and tests/ importable in child processes too.

Several tests start real host/companion subprocesses; they inherit PYTHONPATH,
which the pytest.ini `pythonpath` option does not set.
"""
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PATHS = [os.path.join(_ROOT, "src"), os.path.join(_ROOT, "tests")]
_existing = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = os.pathsep.join(_PATHS + ([_existing] if _existing else []))
