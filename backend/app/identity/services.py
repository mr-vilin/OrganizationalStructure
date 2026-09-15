import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class SessionIdentity:
    open_id: str
    session_id: str
    csrf_digest: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    csrf_token: str


class SessionService:
    def __init__(self, secret: str, allowlist: set[str], ttl: timedelta = timedelta(hours=12)):
        if len(secret) < 32:
            raise ValueError("session secret must contain at least 32 characters")
        self._secret = secret.encode()
        self._allowlist = set(allowlist)
        self._ttl = ttl
        self._revoked: set[str] = set()

    def set_allowlist(self, allowlist: set[str]) -> None:
        self._allowlist = set(allowlist)

    def create(self, open_id: str, now: datetime | None = None) -> IssuedSession | None:
        if open_id not in self._allowlist:
            return None
        now = now or datetime.now(timezone.utc)
        session_id, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        payload = {"oid": open_id, "sid": session_id, "csrf": self._digest(csrf), "exp": int((now + self._ttl).timestamp())}
        raw = _b64(json.dumps(payload, separators=(",", ":")).encode())
        signature = _b64(hmac.new(self._secret, raw.encode(), hashlib.sha256).digest())
        return IssuedSession(f"{raw}.{signature}", csrf)

    def authenticate(self, token: str | None, now: datetime | None = None) -> SessionIdentity | None:
        if not token:
            return None
        now = now or datetime.now(timezone.utc)
        try:
            raw, provided_signature = token.split(".", 1)
            expected = _b64(hmac.new(self._secret, raw.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(provided_signature, expected):
                return None
            payload = json.loads(_unb64(raw))
            expires = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        except (ValueError, KeyError, json.JSONDecodeError):
            return None
        if expires <= now or payload["sid"] in self._revoked or payload["oid"] not in self._allowlist:
            return None
        return SessionIdentity(payload["oid"], payload["sid"], payload["csrf"], expires)

    def revoke(self, session_id: str) -> None:
        self._revoked.add(session_id)

    def verify_csrf(self, identity: SessionIdentity, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(identity.csrf_digest, self._digest(token))

    def _digest(self, value: str) -> str:
        return hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ApiClientRecord:
    client_id: str
    name: str
    secret_hash: str
    created_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class IssuedApiCredential:
    client_id: str
    secret: str


class ApiCredentialService:
    def __init__(self, pepper: str):
        self._pepper = pepper.encode()
        self._records: dict[str, ApiClientRecord] = {}

    def issue(self, name: str, now: datetime | None = None) -> IssuedApiCredential:
        now = now or datetime.now(timezone.utc)
        client_id, secret = secrets.token_urlsafe(12), secrets.token_urlsafe(32)
        record = ApiClientRecord(client_id, name.strip(), self._hash(secret), now)
        self._records[client_id] = record
        return IssuedApiCredential(client_id, secret)

    def authenticate(self, client_id: str, secret: str, now: datetime | None = None) -> ApiClientRecord | None:
        record = self._records.get(client_id)
        if record is None or record.revoked_at is not None:
            return None
        return record if hmac.compare_digest(record.secret_hash, self._hash(secret)) else None

    def revoke(self, client_id: str, now: datetime | None = None) -> None:
        record = self._records.get(client_id)
        if record is not None:
            self._records[client_id] = ApiClientRecord(record.client_id, record.name, record.secret_hash, record.created_at, now or datetime.now(timezone.utc))

    def rotate(self, client_id: str, now: datetime | None = None) -> IssuedApiCredential:
        record = self._records[client_id]
        self.revoke(client_id, now)
        return self.issue(record.name, now)

    def export_records(self) -> list[ApiClientRecord]:
        return list(self._records.values())

    def _hash(self, secret: str) -> str:
        salt = hashlib.sha256(self._pepper).digest()
        return hashlib.scrypt(secret.encode(), salt=salt, n=2**14, r=8, p=1).hex()

