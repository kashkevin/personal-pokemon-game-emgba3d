"""The CI helper that admits a private release input only when its pinned hash matches."""
import hashlib
import importlib.util
import io
from pathlib import Path
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/windows-runtime/fetch_private_input.py"
spec = importlib.util.spec_from_file_location("fetch_private_input", SCRIPT)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

DATA = b"private bytes" * 1000
PIN = hashlib.sha256(DATA).hexdigest()


def run(tmp_path, monkeypatch, *extra, env=None):
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["x", "--dest", str(tmp_path / "out/file.bin"), "--sha256", PIN,
                                      "--max-bytes", "100000", *extra])
    return helper.main()


def test_local_file_with_the_pinned_hash_is_accepted(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/file.bin").write_bytes(DATA)
    assert run(tmp_path, monkeypatch, "--local-dir", str(tmp_path / "src"), "--local-name", "file.bin") == 0
    assert (tmp_path / "out/file.bin").read_bytes() == DATA


def test_wrong_bytes_are_refused_and_leave_nothing(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/file.bin").write_bytes(DATA + b"!")
    assert run(tmp_path, monkeypatch, "--local-dir", str(tmp_path / "src"), "--local-name", "file.bin") == 1
    assert list((tmp_path / "out").iterdir()) == []


def test_input_over_the_bound_is_refused(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/file.bin").write_bytes(DATA)
    monkeypatch.setattr(sys, "argv", ["x", "--dest", str(tmp_path / "o.bin"), "--sha256", PIN, "--max-bytes", "10",
                                      "--local-dir", str(tmp_path / "src"), "--local-name", "file.bin"])
    assert helper.main() == 1 and not (tmp_path / "o.bin").exists()


def test_nothing_supplied_is_optional_not_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("PRIVATE_TEST_URL", raising=False)
    assert run(tmp_path, monkeypatch, "--url-env", "PRIVATE_TEST_URL") == helper.NOT_SUPPLIED


def test_plain_http_url_is_refused(tmp_path, monkeypatch):
    assert run(tmp_path, monkeypatch, "--url-env", "PRIVATE_TEST_URL",
               env={"PRIVATE_TEST_URL": "http://example.invalid/x"}) == 1


def test_https_download_is_verified_and_masked(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(helper.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(DATA))
    assert run(tmp_path, monkeypatch, "--url-env", "PRIVATE_TEST_URL",
               env={"PRIVATE_TEST_URL": "https://example.invalid/secret-token"}) == 0
    out = capsys.readouterr()
    assert "::add-mask::https://example.invalid/secret-token" in out.out
    assert "secret-token" not in out.err and (tmp_path / "out/file.bin").read_bytes() == DATA


def test_a_bad_pin_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x", "--dest", str(tmp_path / "o"), "--sha256", "abc", "--max-bytes", "1"])
    assert helper.main() == 1
