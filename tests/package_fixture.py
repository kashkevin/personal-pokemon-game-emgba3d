"""A packaged installation the way the Windows package lays it out, built from synthetic inputs.

``Package`` writes the application folder PyInstaller produces (``_internal``: game-manifest.json
and runtime\\ with the native games, SDL2.dll, a battle picture pack and the pinned game facts) with
the same tool the CI uses (scripts/windows-runtime/collect_native_bundle.py), plus a private folder
that has no game.gba. The fixture bytes are not a game; they test identity and integrity only.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import sys

from emerald_multiplayer.launcher_gui import LauncherRelease
from test_host_world import make_trade_files

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/windows-runtime"))
import collect_native_bundle  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Package:
    def __init__(self, root, *, rom=None, manifest=None, facts=True, sprites=True):
        self.root = Path(root)
        inputs = self.root / "inputs"
        inputs.mkdir(parents=True)
        if rom is None:
            rom, manifest = make_trade_files(inputs)
        self.rom, self.manifest = Path(rom), Path(manifest)
        (inputs / "pokeemerald-mp-diorama.exe").write_bytes(b"MZ synthetic 3D game, never executed")
        (inputs / "pokeemerald-mp.exe").write_bytes(b"MZ synthetic Classic 2D game, never executed")
        (inputs / "SDL2.dll").write_bytes(b"synthetic SDL stand-in")
        extra = []
        if sprites:
            (inputs / "battle-sprites.ebsp").write_bytes(b"synthetic battle picture pack")
            extra.append(inputs / "battle-sprites.ebsp")
        # The PyInstaller onedir: EmeraldTogether.exe beside _internal (sys._MEIPASS).
        self.application = self.root / "EmeraldTogether" / "_internal"
        self.application.mkdir(parents=True)
        shutil.copyfile(self.manifest, self.application / "game-manifest.json")
        collect_native_bundle.collect(inputs / "pokeemerald-mp-diorama.exe", inputs / "SDL2.dll", self.rom,
                                      self.application / "runtime", extra,
                                      classic_game=inputs / "pokeemerald-mp.exe",
                                      manifest=self.manifest if facts else None)
        self.private = self.root / "LocalAppData" / "PokemonPrivate" / "launcher"
        self.private.mkdir(parents=True)
        self.release = LauncherRelease("Test 1", sha(self.rom), sha(self.application / "game-manifest.json"),
                                       sha(self.runtime / "runtime.json"))

    @property
    def runtime(self):
        return self.application / "runtime"

    def installation(self):
        return self.release.installation(self.application, self.private)
