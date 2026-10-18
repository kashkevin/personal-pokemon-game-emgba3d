"""Portable, secret-bearing friend invitations for an explicitly pinned world.

No listener, game process, system trust store, or server credential exchange is
started here. An invitation is a private capability for exactly one account.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID

from .companion import CompanionConfig, BASELINE_RULESET, verify_rom_manifest
from .gen6_profile import GEN6_DEFAULTS_RULESET
from .ownership import OWNERSHIP_PROFILE
from .secure_transport import ClientTlsConfig, is_numeric_unicast_address

INVITATION_FORMAT = "emerald-private-invitation-v1"
MAX_INVITATION_BYTES = 16_384
_FIELDS = frozenset({"format", "role", "slot", "world_id", "player_id", "display_name",
                     "credential", "endpoint", "port", "build_id", "ruleset_id", "save_profile",
                     "certificate_pem", "certificate_sha256"})


class InvitationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _uuid(value):
    try:
        valid = type(value) is str and str(UUID(value)) == value and UUID(value).int != 0
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise InvitationError("invalid_invitation", "invitation identity must be a nonzero canonical UUID")


def _name(value):
    if type(value) is not str or not 1 <= len(value) <= 24 or not value.strip() or not value.isprintable():
        raise InvitationError("invalid_invitation", "player name must contain 1 to 24 printable characters")


def _endpoint(value, port):
    if type(value) is not str or not is_numeric_unicast_address(value):
        raise InvitationError("invalid_endpoint", "invitation requires a numeric unicast endpoint")
    if str(ipaddress.ip_address(value)) != value:
        raise InvitationError("invalid_endpoint", "invitation endpoint must use its canonical numeric form")
    if type(port) is not int or not 1 <= port <= 65535:
        raise InvitationError("invalid_endpoint", "invitation port must be between 1 and 65535")


def _hash(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _json(data, maximum=MAX_INVITATION_BYTES):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    if type(data) is not bytes or not 1 <= len(data) <= maximum:
        raise InvitationError("invalid_invitation", "invitation exceeds its bounded format")
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise InvitationError("invalid_invitation", "invitation JSON is invalid or contains duplicate keys") from None
    if type(result) is not dict:
        raise InvitationError("invalid_invitation", "invitation must be a JSON object")
    return result


def _bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _regular(path, maximum=None):
    path = Path(path)
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size < 1
                or (maximum is not None and info.st_size > maximum)):
            raise ValueError()
        return path
    except (OSError, ValueError):
        raise InvitationError("invalid_file", "expected a bounded regular private file") from None


def _read(path, maximum):
    path = _regular(path, maximum)
    try:
        with path.open("rb") as stream:
            value = stream.read(maximum + 1)
        if len(value) > maximum:
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise InvitationError("invalid_file", "expected a bounded regular private file") from None


def _write_new(path, data):
    """Never replace an existing capability, key, descriptor, or trust file."""
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    if os.name != "nt":
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _certificate(pem, world_id, pin, *, now=None):
    """Validate the v1 self-signed host identity without touching system trust."""
    if type(pem) is not str or not 1 <= len(pem) <= 8192 or not _hash(pin):
        raise InvitationError("certificate_invalid", "invitation certificate or pin is invalid")
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError:
        raise InvitationError("dependency_missing", "host provisioning requires the pinned cryptography dependency") from None
    try:
        encoded = pem.encode("ascii")
        cert = x509.load_pem_x509_certificate(encoded)
        der = cert.public_bytes(serialization.Encoding.DER)
        key = cert.public_key()
        usage = cert.extensions.get_extension_for_class(x509.KeyUsage)
        constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        authority = cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value
        subject = cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        current = now or datetime.now(timezone.utc)
        if (cert.public_bytes(serialization.Encoding.PEM) != encoded
                or not hmac.compare_digest(hashlib.sha256(der).hexdigest(), pin)
                or cert.subject != cert.issuer
                or cert.subject != x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Emerald world " + world_id)])
                or not isinstance(key, rsa.RSAPublicKey) or key.key_size != 3072
                or not isinstance(cert.signature_hash_algorithm, hashes.SHA256)
                or not cert.not_valid_before_utc <= current < cert.not_valid_after_utc
                or not constraints.critical or not constraints.value.ca or constraints.value.path_length != 0
                or not usage.critical or not usage.value.digital_signature or not usage.value.key_cert_sign
                or authority.key_identifier != subject.digest
                or list(eku) != [ExtendedKeyUsageOID.SERVER_AUTH]):
            raise ValueError()
        key.verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm)
        return cert
    except Exception:
        raise InvitationError("certificate_invalid", "host certificate is expired, incompatible, or does not match its pin/world") from None


@dataclass(frozen=True)
class Invitation:
    role: str
    slot: int
    world_id: str
    player_id: str
    display_name: str
    credential: bytes = field(repr=False)
    endpoint: str
    port: int
    build_id: str
    ruleset_id: str
    save_profile: str
    certificate_pem: str = field(repr=False)
    certificate_sha256: str

    def __post_init__(self):
        if (type(self.slot) is not int or not 0 <= self.slot <= 3
                or self.role != ("host" if self.slot == 0 else "friend")):
            raise InvitationError("invalid_role", "host slot zero and three separate friend slots are required")
        _uuid(self.world_id)
        _uuid(self.player_id)
        _name(self.display_name)
        _endpoint(self.endpoint, self.port)
        if (type(self.credential) is not bytes or len(self.credential) != 32
                or not _hash(self.build_id)
                or self.ruleset_id not in (BASELINE_RULESET, GEN6_DEFAULTS_RULESET)
                or self.save_profile != OWNERSHIP_PROFILE):
            raise InvitationError("invalid_invitation", "invitation credential or game profile is incompatible")
        _certificate(self.certificate_pem, self.world_id, self.certificate_sha256)

    @classmethod
    def loads(cls, data):
        value = _json(data)
        if set(value) != _FIELDS or value.pop("format") != INVITATION_FORMAT:
            raise InvitationError("invalid_invitation", "invitation fields or version are incompatible")
        if value["role"] != "friend":
            raise InvitationError("invalid_role", "portable invitations are only for separate friend accounts")
        credential = value.get("credential")
        if not _hash(credential):
            raise InvitationError("invalid_invitation", "invitation credential must contain 32 encoded bytes")
        value["credential"] = bytes.fromhex(credential)
        return cls(**value)

    @classmethod
    def load(cls, path):
        return cls.loads(_read(path, MAX_INVITATION_BYTES))

    def dumps(self):
        if self.role != "friend":
            raise InvitationError("invalid_role", "portable invitations cannot contain the host account")
        value = {name: getattr(self, name) for name in _FIELDS if name != "format"}
        value.update(format=INVITATION_FORMAT, credential=self.credential.hex())
        encoded = _bytes(value)
        if len(encoded) > MAX_INVITATION_BYTES:
            raise InvitationError("invalid_invitation", "invitation exceeds its bounded format")
        return encoded

    def save(self, path):
        _certificate(self.certificate_pem, self.world_id, self.certificate_sha256)
        _write_new(path, self.dumps())

    def companion_config(self, rom_path, manifest_path, *, token, private_directory, ipc_port=0):
        """Import dedicated trust and return a config; never connect or launch."""
        build, manifest = verify_rom_manifest(Path(rom_path), Path(manifest_path))
        if (build != self.build_id or manifest.get("ruleset_id") != self.ruleset_id
                or manifest.get("save_profile") != self.save_profile or manifest.get("trade_abi_version") != 1):
            raise InvitationError("build_mismatch", "invitation requires the exact installed ownership/trade game build")
        _certificate(self.certificate_pem, self.world_id, self.certificate_sha256)
        root = Path(private_directory).absolute()
        if root.is_symlink():
            raise InvitationError("invalid_file", "private invitation directory cannot be linked")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        trust = root / ("host-" + self.certificate_sha256 + ".pem")
        if trust.exists() or trust.is_symlink():
            if _read(trust, 8192) != self.certificate_pem.encode("ascii"):
                raise InvitationError("certificate_invalid", "existing private trust file differs from this invitation")
        else:
            _write_new(trust, self.certificate_pem.encode("ascii"))
        # The account's remembered route (network_settings.save_join_route): direct, or through the world's relay. Only where to
        # knock changes; the pinned certificate, the credential and the expected world are the same either way.
        from .network_settings import load_join_route
        relay = load_join_route(root) if self.role == "friend" else None
        return CompanionConfig(Path(rom_path), Path(manifest_path), self.player_id, self.display_name, token,
            server_host=self.endpoint, server_port=self.port, ipc_port=ipc_port,
            server_credential=self.credential, server_tls=ClientTlsConfig(trust, self.certificate_sha256),
            public_server=True, expected_world_id=self.world_id,
            relay_host=None if relay is None else relay[0], relay_port=None if relay is None else relay[1])
