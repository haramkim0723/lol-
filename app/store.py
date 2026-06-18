from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .engine import new_state


class JsonStore:
    def __init__(self, path: str | None = None):
        self.path = Path(path or os.getenv("DATA_FILE", "data/state.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return new_state()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return new_state()

    def save(self) -> None:
        payload = json.dumps(self.state, ensure_ascii=False, indent=2)
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

