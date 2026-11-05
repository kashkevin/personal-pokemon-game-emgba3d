"""Private schema-3 world/account provisioning, without booting a listener.

Opening existing worlds validates them without changing epochs, credentials,
enrollment, canonical checkpoints, or certificate identity. The one file an open
may write is world.sqlite3.save-readings, the check's remembered save readings
(save_readings.py): no world data, and deleting it only makes the next open slower.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import secrets

from .companion import BASELINE_RULESET, verify_rom_manifest
from .gen6_profile import GEN6_DEFAULTS_RULESET
from .invitations import (Invitation, InvitationError, _bytes, _certificate, _endpoint,
                          _hash, _json, _name, _read, _regular, _uuid, _write_new)
from .ownership import OWNERSHIP_PROFILE
from .secure_transport import ServerTlsConfig
from .storage import BUSY_TIMEOUT, StorageError, _ExclusiveFileLock
from .trade_storage import TradeCheckpointStore
from .windows_files import replace_file, unlink_file

HOST_FORMAT = "emerald-private-host-v1"
_FIELDS = frozenset({"format", "world_id", "build_id", "ruleset_id", "save_profile", "endpoint",
                     "port", "certificate_sha256", "accounts"})
_ACCOUNT_FIELDS = frozenset({"role", "slot", "player_id", "display_name", "credential"})
# A friend's invite code being replaced (KNOWN_ISSUES NU-7): the new credential, written before anything else changes.
REPLACEMENT_FILE = "credential-replacement.json"
REPLACEMENT_FORMAT = "emerald-credential-replacement-v1"
_REPLACEMENT_FIELDS = frozenset({"format", "world_id", "slot", "player_id", "credential"})


class HostWorldError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class HostAccount:
    role: str
    slot: int
    player_id: str
    display_name: str
    credential: bytes = field(repr=False)

    def __post_init__(self):
        if type(self.slot) is not int or not 0 <= self.slot <= 3 or self.role != ("host" if self.slot == 0 else "friend"):
            raise HostWorldError("invalid_profile", "host/friend roles must match the four distinct account slots")
        _uuid(self.player_id)
        _name(self.display_name)
        if type(self.credential) is not bytes or len(self.credential) != 32:
            raise HostWorldError("invalid_profile", "private account credential is invalid")


def _build(rom_path, manifest_path):
    build, manifest = verify_rom_manifest(Path(rom_path), Path(manifest_path))
    if (manifest.get("trade_abi_version") != 1 or manifest.get("save_profile") != OWNERSHIP_PROFILE
            or manifest.get("ruleset_id") not in (BASELINE_RULESET, GEN6_DEFAULTS_RULESET)):
        raise HostWorldError("build_mismatch", "host provisioning requires the verified ownership/trade game build")
    return build, manifest["ruleset_id"], manifest


def _new_certificate(world_id, endpoint, validity_days):
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError:
        raise HostWorldError("dependency_missing", "host provisioning requires the pinned cryptography dependency") from None
    import ipaddress
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Emerald world " + world_id)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=validity_days))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=False,
                encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(endpoint))]), critical=False)
            .sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pin = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    _certificate(pem.decode("ascii"), world_id, pin)
    return pem, private, pin


def _owner_lock(root):
    """The lock a hosting server holds for its whole run (storage.CheckpointStore.begin_server_boot)."""
    return _ExclusiveFileLock(root / "world.sqlite3.owner.lock")


def _sync_directory(root):
    if os.name != "nt":
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _replace(path, data):
    """``path``'s content replaced whole: a new file beside it, synced, then moved over it."""
    staged = path.with_name(path.name + ".new")
    if staged.exists() or staged.is_symlink():
        unlink_file(staged)                     # a replacement stopped before its move: never read
    _write_new(staged, data)
    replace_file(staged, path)
    _sync_directory(path.parent)


def _apply_replacement(root, build, rules):
    """Finish the code replacement whose record is in ``root`` (the world's owner lock held). The record holds the new
    credential and was whole on disk before the database or host.json changed, so finishing is always possible, and the
    same steps again change nothing. A record that cannot be read was cut short while being written, before anything
    else changed: it is removed."""
    path = root / REPLACEMENT_FILE
    if not path.exists() and not path.is_symlink():
        return
    value = _json(_read(root / "host.json", 16_384))
    accounts = value.get("accounts") if type(value) is dict else None
    if type(accounts) is not list or not all(type(a) is dict for a in accounts) or type(value.get("world_id")) is not str:
        raise HostWorldError("world_invalid", "host descriptor is unreadable")
    try:
        record = _json(_read(path, 4096))
        if (type(record) is not dict or set(record) != _REPLACEMENT_FIELDS or record["format"] != REPLACEMENT_FORMAT
                or record["world_id"] != value["world_id"] or type(record["slot"]) is not int
                or not 1 <= record["slot"] < len(accounts) or record["player_id"] != accounts[record["slot"]].get("player_id")
                or not _hash(record["credential"])):
            raise ValueError()
    except (InvitationError, ValueError):
        unlink_file(path)
        _sync_directory(root)
        return
    try:
        _regular(root / "world.sqlite3")      # never let a store constructor create a missing database
    except InvitationError:
        raise HostWorldError("world_invalid", "the world's database is missing") from None
    with TradeCheckpointStore(root / "world.sqlite3", build, rules, OWNERSHIP_PROFILE, save_readings=True) as store:
        if store.metadata.world_id != value["world_id"]:
            raise HostWorldError("world_invalid", "database belongs to another world")
        store.replace_credential(record["player_id"], bytes.fromhex(record["credential"]))
    if accounts[record["slot"]].get("credential") != record["credential"]:
        accounts[record["slot"]]["credential"] = record["credential"]
        _replace(root / "host.json", _bytes(value))
    unlink_file(path)
    _sync_directory(root)


def _finish_replacement(root, build, rules):
    """A replacement left half done (the game or the PC stopped during HostWorld.replace_credential), finished before the
    world is opened. Refused while another process holds the world's owner lock (hosting it, or replacing a code)."""
    lock = _owner_lock(root)
    try:
        lock.acquire()
    except OSError:
        raise HostWorldError("world_busy", "this world is being hosted or one of its invite codes is being replaced") from None
    try:
        _apply_replacement(root, build, rules)
    except StorageError as error:
        raise HostWorldError("world_invalid", "the database refused the replaced invite code: " + error.code) from None
    finally:
        lock.release()


@dataclass(frozen=True)
class HostWorld:
    directory: Path
    world_id: str
    build_id: str
    ruleset_id: str
    save_profile: str
    endpoint: str
    port: int
    certificate_sha256: str
    accounts: tuple[HostAccount, ...]

    @property
    def database_path(self):
        return self.directory / "world.sqlite3"

    @property
    def server_tls(self):
        return ServerTlsConfig(self.directory / "host-certificate.pem", self.directory / "host-key.pem")

    @classmethod
    def create(cls, directory, rom_path, manifest_path, *, player_names, endpoint, port, validity_days=365,
               trade_effect_policy=None):
        """Create a new private directory; failed partials stay marked in place."""
        build, rules, manifest = _build(rom_path, manifest_path)
        from .trade_effect_preparation import POLICIES
        effects = manifest.get("trade_replay_abi_version") == 1
        if (effects and trade_effect_policy not in POLICIES
                or not effects and trade_effect_policy is not None):
            raise HostWorldError("trade_effect_policy_required", "select an explicit compatible handler policy for this game")
        _endpoint(endpoint, port)
        if (type(player_names) not in (tuple, list) or not 1 <= len(player_names) <= 4
                or type(validity_days) is not int or not 1 <= validity_days <= 3650):
            raise HostWorldError("invalid_profile", "one host plus at most three friends and bounded certificate validity are required")
        for name in player_names:
            _name(name)
        root = Path(directory).absolute()
        # No path is moved or recursively removed. Existing worlds are refused.
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        store = None
        try:
            store = TradeCheckpointStore(root / "world.sqlite3", build, rules, OWNERSHIP_PROFILE, save_readings=True)
            world_id = store.metadata.world_id
            pem, private, pin = _new_certificate(world_id, endpoint, validity_days)
            _write_new(root / "host-certificate.pem", pem)
            _write_new(root / "host-key.pem", private)
            accounts = tuple(HostAccount("host" if i == 0 else "friend", i, identity.player_id,
                                       identity.display_name, identity.credential)
                             for i, name in enumerate(player_names) for identity in (store.create_player(name),))
            if manifest.get("battle_execution_abi_version") == 1:
                from .battle_reservations import enable_battle_reservations
                enable_battle_reservations(store, root / "before-battle-reservations.sqlite3")
            if manifest.get("reset_abi_version") in (1, 2):
                from .reset_attempts import enable_reset_attempts
                enable_reset_attempts(store, root / "before-personal-attempts.sqlite3")
            # Universal characters (character_transfers.py): every new world can take its characters back.
            from .character_transfers import enable_character_transfers
            enable_character_transfers(store, root / "before-character-transfers.sqlite3")
            if effects:
                from .trade_friendship_migration import enable_friendship_history
                from .trade_effect_storage import enable_trade_effects
                enable_friendship_history(store, root / "before-handler-history.sqlite3")
                enable_trade_effects(store, root / "before-native-trade-effects.sqlite3", policy_id=trade_effect_policy)
            descriptor = dict(format=HOST_FORMAT, world_id=world_id, build_id=build, ruleset_id=rules,
                              save_profile=OWNERSHIP_PROFILE, endpoint=endpoint, port=port, certificate_sha256=pin,
                              accounts=[dict(role=p.role, slot=p.slot, player_id=p.player_id,
                                             display_name=p.display_name, credential=p.credential.hex()) for p in accounts])
            store.integrity_check()
            _write_new(root / "host.json", _bytes(descriptor))
        except BaseException:
            # Preserve recoverable artifacts, including credentials/keys that
            # may already exist. No exception details or secrets enter markers.
            try:
                _write_new(root / "creation-failed.json", _bytes({"format": HOST_FORMAT, "failed": True}))
            except OSError:
                pass
            raise
        finally:
            if store is not None:
                store.close()
        try:
            return cls.open(root, rom_path, manifest_path)
        except BaseException:
            try:
                _write_new(root / "creation-failed.json", _bytes({"format": HOST_FORMAT, "failed": True}))
            except OSError:
                pass
            raise

    @classmethod
    def open(cls, directory, rom_path, manifest_path):
        build, rules, _ = _build(rom_path, manifest_path)
        root = Path(directory).absolute()
        if root.is_symlink() or not root.is_dir() or (root / "creation-failed.json").exists():
            raise HostWorldError("world_invalid", "host directory is missing, linked, or has an incomplete creation")
        if (root / REPLACEMENT_FILE).exists() or (root / REPLACEMENT_FILE).is_symlink():
            _finish_replacement(root, build, rules)
        value = _json(_read(root / "host.json", 16_384))
        if (set(value) != _FIELDS or value["format"] != HOST_FORMAT or value["build_id"] != build
                or value["ruleset_id"] != rules or value["save_profile"] != OWNERSHIP_PROFILE):
            raise HostWorldError("world_invalid", "host descriptor is incompatible with the installed game")
        _uuid(value["world_id"])
        _endpoint(value["endpoint"], value["port"])
        if not _hash(value["certificate_sha256"]):
            raise HostWorldError("world_invalid", "host certificate pin is invalid")
        source = value["accounts"]
        if type(source) is not list or not 1 <= len(source) <= 4:
            raise HostWorldError("world_invalid", "host descriptor needs one to four distinct account profiles")
        accounts = []
        for slot, profile in enumerate(source):
            if type(profile) is not dict or set(profile) != _ACCOUNT_FIELDS or profile["slot"] != slot or not _hash(profile["credential"]):
                raise HostWorldError("world_invalid", "private account fields are invalid")
            accounts.append(HostAccount(profile["role"], profile["slot"], profile["player_id"],
                                        profile["display_name"], bytes.fromhex(profile["credential"])))
        if len({p.player_id for p in accounts}) != len(accounts) or len({p.credential for p in accounts}) != len(accounts):
            raise HostWorldError("world_invalid", "account identities and credentials must be distinct")
        pem = _read(root / "host-certificate.pem", 8192).decode("ascii")
        cert = _certificate(pem, value["world_id"], value["certificate_sha256"])
        private = _read(root / "host-key.pem", 8192)
        try:
            from cryptography.hazmat.primitives import serialization
            key = serialization.load_pem_private_key(private, password=None)
            if key.public_key().public_numbers() != cert.public_key().public_numbers():
                raise ValueError()
            ServerTlsConfig(root / "host-certificate.pem", root / "host-key.pem").build_context()
        except Exception:
            raise HostWorldError("world_invalid", "host certificate and private key are incompatible") from None
        # Refuse a missing DB rather than letting a store constructor create it. Its check reads each save once in its
        # life: the readings are remembered beside it (world.sqlite3.save-readings, save_readings.py; KNOWN_ISSUES MS-161).
        _regular(root / "world.sqlite3")
        with TradeCheckpointStore(root / "world.sqlite3", build, rules, OWNERSHIP_PROFILE, save_readings=True) as store:
            if store.metadata.world_id != value["world_id"]:
                raise HostWorldError("world_invalid", "database belongs to another world")
            if store._connection.execute("SELECT count(*) FROM players").fetchone()[0] != len(accounts):
                raise HostWorldError("world_invalid", "database account roster differs from its private profiles")
            for account in accounts:
                if store.authenticate(account.player_id, account.credential).display_name != account.display_name:
                    raise HostWorldError("world_invalid", "private profile does not match its database account")
            store.integrity_check()
        return cls(root.resolve(), value["world_id"], build, rules, OWNERSHIP_PROFILE,
                   value["endpoint"], value["port"], value["certificate_sha256"], tuple(accounts))

    @classmethod
    def replace_credential(cls, directory, rom_path, manifest_path, slot):
        """A new invite code for the friend in ``slot`` (1 to 3; KNOWN_ISSUES NU-7): a new credential for that account, so
        the old code is refused from now on; the account, its character and saves stay as they are. Only while the world
        is not being hosted (its owner lock free): its sessions are not changed under it. Crash-safe: the new credential
        is written to a record first; the database and host.json follow; the record goes last, and HostWorld.open
        finishes one left half done. Returns the world opened again, with the new credential."""
        world = cls.open(directory, rom_path, manifest_path)
        if type(slot) is not int or not 1 <= slot < len(world.accounts):
            raise HostWorldError("invalid_role", "only a friend's invite code can be replaced")
        lock = _owner_lock(world.directory)
        try:
            lock.acquire()
        except OSError:
            raise HostWorldError("world_hosted", "stop hosting this world before replacing an invite code") from None
        try:
            if (world.directory / REPLACEMENT_FILE).exists() or (world.directory / REPLACEMENT_FILE).is_symlink():
                raise HostWorldError("world_busy", "another replacement is under way")
            taken = {account.credential for account in world.accounts}
            credential = secrets.token_bytes(32)
            while credential in taken:
                credential = secrets.token_bytes(32)
            account = world.accounts[slot]
            _write_new(world.directory / REPLACEMENT_FILE,
                       _bytes(dict(format=REPLACEMENT_FORMAT, world_id=world.world_id, slot=slot,
                                   player_id=account.player_id, credential=credential.hex())))
            _sync_directory(world.directory)
            try:
                _apply_replacement(world.directory, world.build_id, world.ruleset_id)
            except (StorageError, HostWorldError) as error:
                # Refused before anything but the record changed (a database that is busy, full or faulty rolls back;
                # host.json follows the database): the record is withdrawn and the old code stays.
                unlink_file(world.directory / REPLACEMENT_FILE)
                _sync_directory(world.directory)
                raise HostWorldError("not_replaced", "the world's database did not take the new code ("
                                     + getattr(error, "code", "error") + "); nothing was changed") from None
            # An OSError past this point (host.json or the record's removal): the database has the new code and the
            # record stays, so the next open finishes it (KNOWN_ISSUES NU-7).
        finally:
            lock.release()
        replaced = cls.open(directory, rom_path, manifest_path)
        if replaced.accounts[slot].credential != credential:
            raise HostWorldError("not_replaced", "the new code did not take; nothing was changed")
        return replaced

    def open_store(self, *, busy_timeout=BUSY_TIMEOUT):
        """Return an unbooted store; the caller owns its lifetime and boot. `busy_timeout`: how long its transactions
        wait for another connection's lock (a host's start waits longer: storage.STARTUP_BUSY_TIMEOUT)."""
        _regular(self.database_path)
        store = TradeCheckpointStore(self.database_path, self.build_id, self.ruleset_id, self.save_profile,
                                     busy_timeout=busy_timeout, save_readings=True)
        if store.metadata.world_id != self.world_id:
            store.close()
            raise HostWorldError("world_invalid", "database world identity changed")
        return store

    def _invitation(self, slot):
        if type(slot) is not int or not 0 <= slot < len(self.accounts):
            raise HostWorldError("invalid_profile", "this account slot has not been provisioned")
        account = self.accounts[slot]
        return Invitation(account.role, account.slot, self.world_id, account.player_id, account.display_name,
                          account.credential, self.endpoint, self.port, self.build_id, self.ruleset_id, self.save_profile,
                          _read(self.directory / "host-certificate.pem", 8192).decode("ascii"), self.certificate_sha256)

    def invitation(self, slot):
        if type(slot) is not int or slot == 0:
            raise HostWorldError("invalid_role", "friend invitations cannot expose the host account")
        return self._invitation(slot)

    def export_invitation(self, slot, path):
        invitation = self.invitation(slot)
        invitation.save(path)
        return invitation

    def host_companion_config(self, rom_path, manifest_path, *, token, private_directory, ipc_port=0):
        return self._invitation(0).companion_config(rom_path, manifest_path, token=token,
                private_directory=private_directory, ipc_port=ipc_port)
