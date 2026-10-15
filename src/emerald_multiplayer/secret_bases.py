"""The host's book of players' Secret Bases (expansion Phase 6).

Each player's game publishes its own base (extras_mailbox.py); the host keeps
the latest record per player, durably, with the owner's choice of who may see
it, and hands every other game the bases it may show. Rules (owner decision 7
asks for confirmation; these are the defaults and nothing else decides):

* a base is visible to everyone, only to the host-formed teammate, or nobody
  (default: everyone; the owner changes it in the Players menu, My Base);
* a base is never visible to its owner's own game as a visitor record;
* hiding or removing a base sends a withdrawal, so a visitor's save drops it;
* the visiting game keeps the base in its save (the original's own storage), so
  it can enter it, see the decorations and battle the owner's party; the owner's
  decorating is shared the next time the record changes.
"""
from __future__ import annotations

from .extras_mailbox import BASE_BYTES, ExtrasMailboxError, tombstone, validate_base

VISIBILITY = ("everyone", "team", "nobody")
MAX_VIEW = 6

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS secret_bases (
        player_id TEXT PRIMARY KEY, record TEXT NOT NULL, tomb TEXT NOT NULL,
        visibility TEXT NOT NULL, updated INTEGER NOT NULL)""",
)


class SecretBaseError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class SecretBaseBook:
    def __init__(self, db, transaction):
        self._db, self._transaction = db, transaction

    def _row(self, player_id):
        return self._db.execute("SELECT record, tomb, visibility, updated FROM secret_bases WHERE player_id=?",
                                (player_id,)).fetchone()

    def _counter(self) -> int:
        row = self._db.execute("SELECT COALESCE(MAX(updated), 0) FROM secret_bases").fetchone()
        return row[0] + 1

    def state(self, player_id: str) -> dict:
        row = self._row(player_id)
        return {"published": bool(row and row[0]), "visibility": row[2] if row else VISIBILITY[0]}

    def publish(self, player_id: str, record_hex: str | None) -> bool:
        """The player's game published its own base (None: it has none). True if the book changed."""
        if record_hex is None:
            record, tomb = "", None
        else:
            try:
                raw = bytes.fromhex(record_hex) if isinstance(record_hex, str) else b""
                raw = validate_base(raw)
            except (ValueError, ExtrasMailboxError) as error:
                raise SecretBaseError("invalid_secret_base", str(error) or "invalid secret base") from error
            record, tomb = raw.hex(), tombstone(raw).hex()
        row = self._row(player_id)
        if row is None:
            if record_hex is None:
                return False
            with self._transaction():
                self._db.execute("INSERT INTO secret_bases VALUES (?, ?, ?, ?, ?)",
                                 (player_id, record, tomb, VISIBILITY[0], self._counter()))
            return True
        if record_hex is None:
            if not row[0]:
                return False
            with self._transaction():
                self._db.execute("UPDATE secret_bases SET record='', updated=? WHERE player_id=?",
                                 (self._counter(), player_id))
            return True
        if row[0] == record:
            return False
        with self._transaction():
            self._db.execute("UPDATE secret_bases SET record=?, tomb=?, updated=? WHERE player_id=?",
                             (record, tomb, self._counter(), player_id))
        return True

    def set_visibility(self, player_id: str, mode: str) -> bool:
        if mode not in VISIBILITY:
            raise SecretBaseError("invalid_visibility", "choose everyone, team or nobody")
        row = self._row(player_id)
        if row is not None and row[2] == mode:
            return False
        with self._transaction():
            if row is None:
                self._db.execute("INSERT INTO secret_bases VALUES (?, '', '', ?, ?)",
                                 (player_id, mode, self._counter()))
            else:
                self._db.execute("UPDATE secret_bases SET visibility=?, updated=? WHERE player_id=?",
                                 (mode, self._counter(), player_id))
        return True

    def view_for(self, recipient: str, teammate: str | None, roster: list[str]) -> list[dict]:
        """The records this player's game applies: other players' visible bases,
        and a withdrawal for each one that is hidden or gone. Connected players first."""
        rows = self._db.execute(
            "SELECT player_id, record, tomb, visibility FROM secret_bases WHERE player_id<>? ORDER BY updated DESC",
            (recipient,)).fetchall()
        rows.sort(key=lambda row: row[0] not in roster)  # stable: newest first within each group
        out = []
        for player_id, record, tomb, visibility in rows:
            visible = record and (visibility == "everyone" or (visibility == "team" and player_id == teammate))
            payload = record if visible else tomb
            if not payload:
                continue
            slot = roster.index(player_id) if player_id in roster else 0
            out.append({"owner": player_id, "slot": slot % 4, "record": payload})
            if len(out) == MAX_VIEW:
                break
        return out
