"""pytest bootstrap: make src/ and tests/ importable in child processes too.

Several tests start real host/companion subprocesses; they inherit PYTHONPATH,
which the pytest.ini `pythonpath` option does not set.
"""
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PATHS = [os.path.join(_ROOT, "src"), os.path.join(_ROOT, "tests")]
_existing = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = os.pathsep.join(_PATHS + ([_existing] if _existing else []))

if os.name == "nt":
    # Windows: TEMP is often an 8.3 short path (C:\Users\RUNNER~1\AppData\Local\Temp on the CI runner, JOHNDO~1 on a PC
    # whose user name is long), while the app resolves the paths it keeps to their long names, so tests comparing the
    # two failed on the spelling alone (Windows run 304). Temporary folders are made under the long name instead, in
    # this process and in the tests' child processes (Python reads TMPDIR first). Nothing changes where TEMP has none.
    import tempfile
    from pathlib import Path

    _TEMP = str(Path(tempfile.gettempdir()).resolve())
    tempfile.tempdir = _TEMP
    os.environ["TMPDIR"] = _TEMP
