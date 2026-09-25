import json
import os
from pathlib import Path
from typing import Dict


class AppConfig:
    def __init__(self) -> None:
        self.config_dir = Path.home() / ".config" / "commander-deck-builder"
        self.config_path = self.config_dir / "config.json"
        self.data: Dict[str, str] = {}
        self.load()

    def load(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.data = {}
            return

        try:
            self.data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.data = {}

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.chmod(self.config_path, 0o600)

    def get(self, key: str, default: str = "") -> str:
        value = self.data.get(key, default)
        return value if isinstance(value, str) else default

    def set(self, key: str, value: str) -> None:
        self.data[key] = value.strip()
