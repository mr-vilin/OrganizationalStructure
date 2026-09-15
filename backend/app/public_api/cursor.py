import base64
import hashlib
import hmac
import json
from dataclasses import dataclass


class InvalidCursor(ValueError):
    pass


class DatasetChanged(ValueError):
    pass


@dataclass(frozen=True)
class CursorPage:
    last_id: str


class CursorCodec:
    def __init__(self, secret: str):
        self._secret = secret.encode()

    def encode(self, *, epoch: str, version: int, filters: dict, last_id: str) -> str:
        payload = {"epoch": epoch, "version": version, "filters": filters, "last_id": last_id}
        raw = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode()
        signature = hmac.new(self._secret, raw.encode(), hashlib.sha256).hexdigest()
        return f"{raw}.{signature}"

    def decode(self, cursor: str, *, epoch: str, version: int, filters: dict) -> CursorPage:
        try:
            raw, signature = cursor.split(".", 1)
            expected = hmac.new(self._secret, raw.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidCursor("cursor signature is invalid")
            payload = json.loads(base64.urlsafe_b64decode(raw))
        except (ValueError, json.JSONDecodeError) as exc:
            raise InvalidCursor("cursor is malformed") from exc
        if payload["epoch"] != epoch or payload["version"] != version:
            raise DatasetChanged("dataset changed during pagination")
        if payload["filters"] != filters:
            raise InvalidCursor("cursor does not match filters")
        return CursorPage(payload["last_id"])

