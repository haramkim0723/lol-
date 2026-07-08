from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .engine import new_state


class JsonStore:
    def __init__(self, path: str | None = None):
        default_path = (
            "/tmp/lol-auction-state.json"
            if os.getenv("VERCEL")
            else "data/state.json"
        )
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
        self.postgres_url = os.getenv("STATE_DATABASE_URL") or ""
        self.postgres_key = os.getenv("STATE_DATABASE_KEY", "lol-auction:state")
        self.document = self._load()

    @property
    def state(self) -> dict[str, Any]:
        competition = self.active_competition
        if competition is None:
            competition = self.create_competition("기본 대회", save=False)
        return competition["state"]

    @property
    def active_competition(self) -> dict[str, Any] | None:
        active_id = self.document.get("active_competition_id")
        return next(
            (
                competition
                for competition in self.document["competitions"]
                if competition["id"] == active_id
            ),
            None,
        )

    @property
    def persistent(self) -> bool:
        return (
            bool(self.postgres_url)
            or bool(self.redis_url and self.redis_token)
            or not os.getenv("VERCEL")
        )

    def competition_summary(self) -> dict[str, Any]:
        return {
            "active_competition_id": self.document.get("active_competition_id"),
            "competitions": [
                {
                    "id": competition["id"],
                    "name": competition["name"],
                    "mode": competition.get("mode", "auction"),
                    "created_at": competition["created_at"],
                    "player_count": len(competition["state"]["players"]),
                    "team_count": len(
                        competition["state"]["tournament"]["teams"]
                    ),
                    "tournament_status": competition["state"]["tournament"][
                        "status"
                    ],
                }
                for competition in self.document["competitions"]
            ],
        }

    def create_competition(
        self, name: str, mode: str = "auction", *, save: bool = True
    ) -> dict[str, Any]:
        competition = {
            "id": uuid.uuid4().hex,
            "name": name.strip(),
            "mode": mode,
            "created_at": __import__("time").time(),
            "state": new_state(),
        }
        competition["state"]["settings"]["room_name"] = name.strip()
        self.document["competitions"].append(competition)
        self.document["active_competition_id"] = competition["id"]
        if save:
            self.save()
        return competition

    def select_competition(self, competition_id: str) -> None:
        if not any(
            item["id"] == competition_id
            for item in self.document["competitions"]
        ):
            raise ValueError("대회를 찾을 수 없습니다.")
        self.document["active_competition_id"] = competition_id
        self.save()

    def delete_competition(self, competition_id: str) -> None:
        before = len(self.document["competitions"])
        self.document["competitions"] = [
            item
            for item in self.document["competitions"]
            if item["id"] != competition_id
        ]
        if len(self.document["competitions"]) == before:
            raise ValueError("대회를 찾을 수 없습니다.")
        if not self.document["competitions"]:
            self.create_competition("기본 대회", save=False)
        elif self.document.get("active_competition_id") == competition_id:
            self.document["active_competition_id"] = self.document[
                "competitions"
            ][0]["id"]
        self.save()

    def refresh(self) -> None:
        if self.postgres_url:
            result = self._postgres_load()
            if result:
                self.document = self._normalize_document(result)
            return
        if not (self.redis_url and self.redis_token):
            return
        result = self._redis_command(["GET", self.redis_key])
        if result:
            self.document = self._normalize_document(json.loads(result))

    def _load(self) -> dict[str, Any]:
        raw: dict[str, Any] | None = None
        if self.postgres_url:
            try:
                raw = self._postgres_load()
            except OSError:
                raw = None
        if raw is None and self.redis_url and self.redis_token:
            try:
                result = self._redis_command(["GET", self.redis_key])
                if result:
                    raw = json.loads(result)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        if raw is None and self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return self._normalize_document(raw or new_state())

    def save(self) -> None:
        payload = json.dumps(self.document, ensure_ascii=False, indent=2)
        if self.postgres_url:
            self._postgres_save(self.document)
            return
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
        competition = self.active_competition
        if competition is None:
            competition = self.create_competition("기본 대회", save=False)
        name = competition["name"]
        competition["state"] = new_state()
        competition["state"]["settings"]["room_name"] = name
        self.save()

    def _normalize_event(self, state: dict[str, Any]) -> dict[str, Any]:
        defaults = new_state()
        state.setdefault("tournament", defaults["tournament"])
        state.setdefault("participation", defaults["participation"])
        state.setdefault("scrim_results", defaults["scrim_results"])
        state.setdefault("settings", defaults["settings"])
        state.setdefault("captains", [])
        state.setdefault("players", [])
        state.setdefault("auction", defaults["auction"])
        for player in state["players"]:
            player.setdefault("score", 0)
            player.setdefault("secondary_score", player["score"])
        return state

    def _normalize_document(self, raw: dict[str, Any]) -> dict[str, Any]:
        if "competitions" not in raw:
            event = self._normalize_event(raw)
            competition_id = uuid.uuid4().hex
            return {
                "version": 2,
                "active_competition_id": competition_id,
                "competitions": [
                    {
                        "id": competition_id,
                        "name": event["settings"].get(
                            "room_name", "기본 대회"
                        ),
                        "mode": "auction",
                        "created_at": __import__("time").time(),
                        "state": event,
                    }
                ],
            }
        raw.setdefault("version", 2)
        for competition in raw["competitions"]:
            competition.setdefault("mode", "auction")
            competition["state"] = self._normalize_event(
                competition.get("state", new_state())
            )
        if not raw["competitions"]:
            competition_id = uuid.uuid4().hex
            raw["competitions"] = [
                {
                    "id": competition_id,
                    "name": "기본 대회",
                    "mode": "auction",
                    "created_at": __import__("time").time(),
                    "state": new_state(),
                }
            ]
            raw["active_competition_id"] = competition_id
        if not any(
            item["id"] == raw.get("active_competition_id")
            for item in raw["competitions"]
        ):
            raw["active_competition_id"] = raw["competitions"][0]["id"]
        return raw

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

    def _postgres_connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise OSError("psycopg package is required for Postgres state storage") from exc
        return psycopg.connect(self.postgres_url, row_factory=dict_row)

    def _ensure_postgres_table(self, connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
              key TEXT PRIMARY KEY,
              document JSONB NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

    def _postgres_load(self) -> dict[str, Any] | None:
        try:
            with self._postgres_connect() as connection:
                self._ensure_postgres_table(connection)
                row = connection.execute(
                    "SELECT document FROM app_state WHERE key = %s",
                    (self.postgres_key,),
                ).fetchone()
                return row["document"] if row else None
        except Exception as exc:
            raise OSError(f"Postgres state load failed: {exc}") from exc

    def _postgres_save(self, document: dict[str, Any]) -> None:
        try:
            with self._postgres_connect() as connection:
                self._ensure_postgres_table(connection)
                connection.execute(
                    """
                    INSERT INTO app_state (key, document, updated_at)
                    VALUES (%s, %s::jsonb, NOW())
                    ON CONFLICT (key) DO UPDATE
                    SET document = EXCLUDED.document,
                        updated_at = NOW()
                    """,
                    (self.postgres_key, json.dumps(document, ensure_ascii=False)),
                )
        except Exception as exc:
            raise OSError(f"Postgres state save failed: {exc}") from exc
