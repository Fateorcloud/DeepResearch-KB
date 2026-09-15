"""Single-user authentication service with revocable opaque credentials."""

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pwdlib import PasswordHash


SESSION_COOKIE = "drkb_session"
_PASSWORD_HASH = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = _PASSWORD_HASH.hash("deepresearch-kb-invalid-login")


def _now():
    return datetime.now(timezone.utc).isoformat()


def hash_password(password):
    if not isinstance(password, str) or not password:
        raise ValueError("password must not be empty")
    return _PASSWORD_HASH.hash(password)


@dataclass(frozen=True)
class Principal:
    username: str
    kind: str
    credential_id: str
    csrf_token: str | None = None


@dataclass(frozen=True)
class IssuedToken:
    id: str
    label: str
    token: str
    created_at: str


class AuthenticationFailed(Exception):
    pass


class LoginRateLimited(Exception):
    pass


class AuthService:
    def __init__(self, database, *, username=None, password_hash=None,
                 session_secret=None, session_ttl_seconds=86400,
                 login_window_seconds=60, login_max_failures=5):
        self.database = Path(database).resolve()
        self.username = username
        self.password_hash = password_hash
        self.session_secret = session_secret
        self.session_ttl_seconds = session_ttl_seconds
        self.login_window_seconds = login_window_seconds
        self.login_max_failures = login_max_failures
        self.configured = bool(
            username and password_hash and password_hash.startswith("$argon2")
            and session_secret and len(session_secret) >= 32)
        self._sessions = {}
        self._failures = defaultdict(deque)
        self._lock = threading.RLock()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS cli_token (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                token_digest TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                last_used_at TEXT
            )""")

    @classmethod
    def from_env(cls, database):
        return cls(
            database,
            username=os.getenv("DRKB_ADMIN_USERNAME"),
            password_hash=os.getenv("DRKB_ADMIN_PASSWORD_HASH"),
            session_secret=os.getenv("DRKB_SESSION_SECRET"),
        )

    def _digest(self, value):
        secret = (self.session_secret or "unconfigured").encode()
        return hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()

    def _trim_failures(self, client_key, now):
        failures = self._failures[client_key]
        cutoff = now - self.login_window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures

    def login(self, username, password, *, client_key):
        if not self.configured:
            raise AuthenticationFailed
        now = time.monotonic()
        with self._lock:
            failures = self._trim_failures(client_key, now)
            if len(failures) >= self.login_max_failures:
                raise LoginRateLimited
        selected_hash = self.password_hash if hmac.compare_digest(username, self.username) else _DUMMY_PASSWORD_HASH
        try:
            valid = _PASSWORD_HASH.verify(password, selected_hash)
        except Exception:
            valid = False
        if not valid or not hmac.compare_digest(username, self.username):
            with self._lock:
                self._trim_failures(client_key, now).append(now)
            raise AuthenticationFailed
        raw_session = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = time.time() + self.session_ttl_seconds
        with self._lock:
            self._failures.pop(client_key, None)
            self._sessions[self._digest(raw_session)] = (
                self.username, csrf_token, expires_at)
        return raw_session, Principal(
            self.username, "session", self._digest(raw_session), csrf_token)

    def authenticate_session(self, raw_session):
        if not self.configured or not raw_session:
            return None
        digest = self._digest(raw_session)
        with self._lock:
            record = self._sessions.get(digest)
            if record is None:
                return None
            username, csrf_token, expires_at = record
            if expires_at <= time.time():
                self._sessions.pop(digest, None)
                return None
        return Principal(username, "session", digest, csrf_token)

    def logout(self, principal):
        if principal.kind == "session":
            with self._lock:
                self._sessions.pop(principal.credential_id, None)

    def verify_csrf(self, principal, supplied):
        return bool(principal.kind != "session" or (
            supplied and principal.csrf_token
            and hmac.compare_digest(supplied, principal.csrf_token)))

    def issue_cli_token(self, label):
        if not self.configured:
            raise AuthenticationFailed
        if not isinstance(label, str) or not label.strip():
            raise ValueError("token label must not be blank")
        token_id = uuid4().hex
        created_at = _now()
        raw_token = "drkb_" + secrets.token_urlsafe(32)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT INTO cli_token VALUES (?, ?, ?, ?, NULL, NULL)",
                       (token_id, label.strip(), self._digest(raw_token), created_at))
        return IssuedToken(token_id, label.strip(), raw_token, created_at)

    def authenticate_bearer(self, raw_token):
        if not self.configured or not raw_token or not raw_token.startswith("drkb_"):
            return None
        digest = self._digest(raw_token)
        used_at = _now()
        with closing(sqlite3.connect(self.database)) as db, db:
            row = db.execute("""SELECT id FROM cli_token
                WHERE token_digest = ? AND revoked_at IS NULL""", (digest,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE cli_token SET last_used_at = ? WHERE id = ?",
                       (used_at, row[0]))
        return Principal(self.username, "bearer", row[0])

    def list_cli_tokens(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("""SELECT id, label, created_at,
                revoked_at, last_used_at FROM cli_token ORDER BY created_at, id""")]

    def revoke_cli_token(self, token_id):
        with closing(sqlite3.connect(self.database)) as db, db:
            cursor = db.execute("""UPDATE cli_token SET revoked_at = ?
                WHERE id = ? AND revoked_at IS NULL""", (_now(), token_id))
            if cursor.rowcount != 1:
                raise KeyError(token_id)


def main():
    import getpass

    password = getpass.getpass("Admin password: ")
    confirmation = getpass.getpass("Confirm admin password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    print(hash_password(password))


if __name__ == "__main__":
    main()
