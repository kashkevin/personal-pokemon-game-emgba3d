"""Packaging-transform checks use tiny invented fixtures, never game data."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location("source_sanitizer", Path(__file__).parents[1] / "scripts/windows-runtime/sanitize_source.py")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class SourceSanitizerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "original.tar.gz"
        with tarfile.open(self.source, "w:gz") as archive:
            for name, content in (("LICENSE", b"invented notice"), ("src/core.c", b"source"), ("cinema/fixture/test.gb", b"invented fixture")):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                member.mode = 0o644
                member.mtime = 123
                archive.addfile(member, io.BytesIO(content))
        self.original = self.source.read_bytes()
        self.policy = self.root / "policy.json"
        self.rules = dict(format="emerald-mgba-source-filter-v1", upstream_commit="synthetic",
                          source_sha256=hashlib.sha256(self.original).hexdigest(), removed=[dict(
                              path="cinema/fixture/test.gb", size=16, sha256=hashlib.sha256(b"invented fixture").hexdigest(), reason="test")])
        self.rules["removed"][0]["size"] = len(b"invented fixture")
        self.write_policy()

    def write_policy(self):
        self.policy.write_text(json.dumps(self.rules))

    def run_filter(self, stem="clean"):
        return _MODULE.sanitize(self.source, self.root / (stem + ".tar.gz"), self.root / (stem + ".json"), policy_path=self.policy)

    def test_retains_source_and_metadata_and_is_deterministic(self):
        result = self.run_filter()
        self.run_filter("again")
        self.assertEqual((self.root / "clean.tar.gz").read_bytes(), (self.root / "again.tar.gz").read_bytes())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertTrue(result["retained_bytes_and_metadata_identical"])
        with tarfile.open(self.root / "clean.tar.gz") as archive:
            self.assertEqual(archive.getnames(), ["LICENSE", "src/core.c"])
            self.assertEqual(archive.extractfile("LICENSE").read(), b"invented notice")
            self.assertEqual(archive.getmember("src/core.c").mtime, 123)

    def test_rejects_wrong_source_pin_before_creating_output(self):
        self.rules["source_sha256"] = "0" * 64
        self.write_policy()
        with self.assertRaises(ValueError): self.run_filter()
        self.assertFalse((self.root / "clean.tar.gz").exists())

    def test_rejects_wrong_member_hash_and_production_removal(self):
        for update in ({"sha256": "0" * 64}, {"path": "src/core.c"}):
            with self.subTest(update=update):
                self.rules["removed"][0].update(update)
                self.write_policy()
                with self.assertRaises(ValueError): self.run_filter()
                self.assertFalse((self.root / "clean.tar.gz").exists())

    def test_never_overwrites_previous_outputs(self):
        self.run_filter()
        original = (self.root / "clean.tar.gz").read_bytes()
        with self.assertRaises(ValueError): self.run_filter()
        self.assertEqual((self.root / "clean.tar.gz").read_bytes(), original)

    def test_rejects_relative_link_to_removed_fixture(self):
        for link_type, target in ((tarfile.SYMTYPE, "../fixture/test.gb"),
                                  (tarfile.LNKTYPE, "cinema/fixture/test.gb")):
            with self.subTest(link_type=link_type):
                replacement = self.root / "with-link.tar.gz"
                with tarfile.open(self.source) as source, tarfile.open(replacement, "w:gz") as archive:
                    for member in source.getmembers():
                        archive.addfile(member, source.extractfile(member) if member.isfile() else None)
                    member = tarfile.TarInfo("cinema/links/item")
                    member.type = link_type
                    member.linkname = target
                    archive.addfile(member)
                self.rules["source_sha256"] = _MODULE.sha(replacement)
                self.write_policy()
                with self.assertRaisesRegex(ValueError, "depends on removed fixture"):
                    _MODULE.sanitize(replacement, self.root / "clean.tar.gz", self.root / "clean.json", policy_path=self.policy)
                self.assertFalse((self.root / "clean.tar.gz").exists())


if __name__ == "__main__":
    unittest.main()
