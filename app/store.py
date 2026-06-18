from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .engine import new_state


class JsonStore:
    def __init__(self, path: str | None = None):
        default_path = "/tmp/lol-auction-state.json" if os.getenv("VERCEL") else "data/state.json"
        self.path = Path(path or os.getenv("DATA_FILE", default_path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.redis_url = (
            os.getenv("UPSTASH_REDIS_REST_URL")
            or os.getenv("KV_REST_API_URL")
            or ""
        ).rstrip("/")
        self.redis_token = (
            os.getenv("UPSTASH_REDIS_REST_TOKEN")
            or os.getenv("KV_REST_API_TOKEN")
            or ""
        )
        self.redis_key = os.getenv("STATE_REDIS_KEY", "lol-auction:state")
        self.state = self._load()

    @property
    def persistent(self) -> bool:
        return bool(self.redis_url and self.redis_token) or not os.getenv("VERCEL")

    def refresh(self) -> None:
        if not (self.redis_url and self.redis_token):
            return
        result = self._redis_command(["GET", self.redis_key])
        if result:
            self.state = self._normalize(json.loads(result))

    def _load(self) -> dict[str, Any]:
        if self.redis_url and self.redis_token:
            try:
                result = self._redis_command(["GET", self.redis_key])
                if result:
                    return self._normalize(json.loads(result))
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        if not self.path.exists():
            return new_state()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            return self._normalize(state)
        except (json.JSONDecodeError, OSError):
            return new_state()

    def save(self) -> None:
        payload = json.dumps(self.state, ensure_ascii=False, indent=2)
        if self.redis_url and self.redis_token:
            self._redis_command(["SET", self.redis_key, payload])
            return
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            delete=False,
        ) as temp:
            temp.write(payload)
            temp_path = Path(temp.name)
        temp_path.replace(self.path)

    def reset(self) -> None:
        self.state = new_state()
        self.save()

    def _normalize(self, state: dict[str, Any]) -> dict[str, Any]:
        defaults = new_state()
        state.setdefault("tournament", defaults["tournament"])
        for player in state.get("players", []):
            player.setdefault("score", 0)
        return state

    def _redis_command(self, command: list[str]) -> Any:
        request = urllib.request.Request(
            self.redis_url,
            data=json.dumps(command).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.redis_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise OSError(f"Redis 저장소 요청 실패: {exc.code}") from exc
        if payload.get("error"):
            raise OSError(payload["error"])
        return payload.get("result")
