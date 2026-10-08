"""Standalone packaging-tool coverage; no emulator/build or private inputs."""
import argparse
from dataclasses import replace
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/windows-runtime"))
from package_audit import Limits, PackageAuditError, audit_files, audit_tree
import build_launcher


def zipped(entries):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in entries:
            archive.writestr(name, raw)
    return result.getvalue()


def tarred(entries):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w") as archive:
        for name, raw in entries:
            item = tarfile.TarInfo(name)
            item.size = len(raw)
            archive.addfile(item, io.BytesIO(raw))
    return result.getvalue()


class PackageAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def check(self, name, raw, **limits):
        path = self.root / name
        path.write_bytes(raw)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            return audit_files([path], limits=replace(Limits(), **limits))
        finally:
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertEqual(list(self.root.iterdir()), [path])
            path.unlink()

    def test_nested_tar_zip_rejects_known_rom_save_state_and_private_formats(self):
        for name in ("test.GBA", "test.gb", "test.gbc", "test.nds", "test.rom", "test.sav",
                     "test.mvl", "test.ss0", "test.ss12", "test.sqlite3", "test.db-wal",
                     "test.pem", "test.key", "host.json", "invitation.json", "test.sav. ",
                     "test.nes", "test.sfc", "test.smc", "test.n64", "test.z64", "test.v64",
                     "test.pce", "test.sms", "test.gg", "test.sg", "test.gen", "test.32x",
                     "test.iso", "test.gbs", "test.dsv", "test.dss"):
            with self.subTest(name=name), self.assertRaises(PackageAuditError):
                self.check("source.tar.gz", gzip.compress(tarred([("nested.zip", zipped([(name, b"fixture")]))])))

    def test_safe_source_and_relink_objects_are_preserved_without_extraction(self):
        raw = gzip.compress(tarred([("LICENSE", b"retained license"), ("src/core.c", b"int core;"),
            ("libmgba.a", b"!<arch>\nopaque library"), ("frontend/main.obj", b"object bytes"),
            ("test_definition.py", b"filename = 'test.gba'"), ("opaque.bin", b"not classified as a save")]))
        result = self.check("relink.tar.gz", raw)
        self.assertEqual(result["archives"], 2)
        self.assertEqual(result["files_and_members"], 7)
        wrapped = self.check("download.zip", zipped([("runtime/relink.tar.gz", raw)]))
        self.assertEqual(wrapped["archives"], 3)

    def test_renamed_archive_magic_and_compressed_private_name_are_checked(self):
        for name, raw in (("renamed.bin", zipped([("private.sav", b"")])),
                          ("save.gba.gz", gzip.compress(b"fixture")),
                          ("renamed.bin", tarred([("private.pem", b"fixture")]))):
            with self.subTest(name=name), self.assertRaises(PackageAuditError):
                self.check(name, raw)

    def test_private_project_json_is_refused_even_under_an_arbitrary_name(self):
        for marker in ("emerald-private-host-v1", "emerald-private-invitation-v1"):
            with self.subTest(marker=marker), self.assertRaises(PackageAuditError):
                self.check("data.zip", zipped([("friend-2.json", json.dumps({"format": marker}).encode())]))
        self.check("source.zip", zipped([("valid.json", b'{"format":[]}'), ("example.txt", b"credential")]))

    def test_malformed_named_archives_fail_closed(self):
        for name in ("source.tar", "source.tar.gz", "source.zip", "source.xz", "source.rar"):
            with self.subTest(name=name), self.assertRaises(PackageAuditError):
                self.check(name, b"not a valid archive")
        raw = zipped([("source.c", b"text")])
        with self.assertRaises(PackageAuditError):
            self.check("truncated.zip", raw[:-1])

    def test_archive_depth_bound(self):
        raw = zipped([("readme.txt", b"source")])
        raw = zipped([("inner.zip", raw)])
        with self.assertRaisesRegex(PackageAuditError, "nesting"):
            self.check("outer.zip", raw, depth=1)

    def test_member_count_bound_checks_directory_before_zipfile_materialization(self):
        raw = zipped([(f"{n}.txt", b"") for n in range(4)])
        with patch("package_audit.zipfile.ZipFile", side_effect=AssertionError("must not parse yet")):
            with self.assertRaisesRegex(PackageAuditError, "count"):
                self.check("many.zip", raw, members=3)
            forged = bytearray(raw)
            end = forged.rfind(b"PK\x05\x06")
            struct.pack_into("<HH", forged, end + 8, 1, 1)
            with self.assertRaisesRegex(PackageAuditError, "count"):
                self.check("forged.zip", bytes(forged), members=3)

    def test_expanded_byte_and_individual_member_bounds(self):
        with self.assertRaisesRegex(PackageAuditError, "bytes"):
            self.check("large.gz", gzip.compress(b"x" * 10000), expanded_bytes=1000)
        with self.assertRaisesRegex(PackageAuditError, "member"):
            self.check("large.zip", zipped([("huge.txt", b"x" * 1000)]), file_bytes=300)

    def test_traversal_links_and_encrypted_zip_are_refused_without_extraction(self):
        for name in ("../private.txt", "/absolute.txt", "C:\\private.txt"):
            with self.subTest(name=name), self.assertRaises(PackageAuditError):
                self.check("source.tar", tarred([(name, b"")]))
        result = io.BytesIO()
        with tarfile.open(fileobj=result, mode="w") as archive:
            link = tarfile.TarInfo("alias")
            link.type, link.linkname = tarfile.SYMTYPE, "secret.pem"
            archive.addfile(link)
        with self.assertRaises(PackageAuditError):
            self.check("linked.tar", result.getvalue())
        raw = bytearray(zipped([("safe.txt", b"hello")]))
        struct.pack_into("<H", raw, 6, 1)
        struct.pack_into("<H", raw, raw.find(b"PK\x01\x02") + 8, 1)
        with self.assertRaisesRegex(PackageAuditError, "encrypted"):
            self.check("encrypted.zip", bytes(raw))

    def test_tree_audit_checks_nested_payload_and_has_shared_limits(self):
        child = self.root / "runtime"
        child.mkdir()
        (child / "source.zip").write_bytes(zipped([("bad.sav", b"")]))
        with self.assertRaises(PackageAuditError):
            audit_tree(self.root)
        (child / "source.zip").write_bytes(zipped([("okay.c", b"text")]))
        self.assertEqual(audit_tree(self.root)["archives"], 1)
        with self.assertRaises(PackageAuditError):
            audit_tree(self.root, limits=replace(Limits(), members=1))

    def test_source_relative_link_inside_archive_is_retained_without_following(self):
        result = io.BytesIO()
        with tarfile.open(fileobj=result, mode="w") as archive:
            link = tarfile.TarInfo("source/android/src")
            link.type, link.linkname = tarfile.SYMTYPE, "../app/src"
            archive.addfile(link)
        self.assertEqual(self.check("source.tar", result.getvalue())["files_and_members"], 2)

    def test_builder_rejects_runtime_before_creating_output_or_launching_pyinstaller(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        (runtime / "source.tar").write_bytes(tarred([("test.gb", b"fixture")]))
        (runtime / "runtime.json").write_text(json.dumps({"files": {"source.tar": "unused"}}))
        args = argparse.Namespace(output=self.root / "output", version="test", rom_sha256="a" * 64,
            manifest_sha256="b" * 64, runtime_sha256="c" * 64, runtime=runtime,
            rom=self.root / "not-copied.gba", manifest=self.root / "manifest.json")
        with patch.object(build_launcher, "os", SimpleNamespace(name="nt")), \
                patch.object(build_launcher.importlib.metadata, "version", return_value=build_launcher.PYINSTALLER), \
                patch("emerald_multiplayer.launcher_session.GameInstallation"), \
                patch.object(build_launcher.subprocess, "run") as run:
            with self.assertRaises(PackageAuditError):
                build_launcher.build(args)
            self.assertFalse(args.output.exists())
            run.assert_not_called()
