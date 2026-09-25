import re
from pathlib import Path


def sanitize_deck_name(raw_name: str) -> str:
    text = (raw_name or "").strip()
    text = re.sub(r"[^A-Za-z0-9 _-]+", "", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("._-")
    return text or "generated_deck"


def choose_generated_deck_path(output_dir: Path, raw_name: str) -> Path:
    safe_name = sanitize_deck_name(raw_name)
    candidate = output_dir / f"{safe_name}.csv"
    if not candidate.exists():
        return candidate

    suffix = 2
    while True:
        candidate = output_dir / f"{safe_name}_{suffix}.csv"
        if not candidate.exists():
            return candidate
        suffix += 1
