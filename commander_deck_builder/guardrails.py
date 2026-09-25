import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set

from .collection import CollectionStore
from .models import DeckCard

BASIC_LANDS = {"Forest", "Island", "Swamp", "Mountain", "Plains", "Wastes"}
LAND_HINTS = (
    "forest",
    "island",
    "swamp",
    "mountain",
    "plains",
    "wastes",
    "tower",
    "passage",
    "landscape",
    "expanse",
    "wilds",
    "barrens",
    "terrace",
    "field",
    "quarter",
    "citadel",
    "palace",
    "maze",
    "thicket",
    "beacon",
    "tunnel",
    "village",
    "town",
    "grotto",
    "arena",
    "temple",
    "path",
    "haven",
    "sanctuary",
    "bridge",
    "desert",
)


class ColorIdentityCache:
    def __init__(self) -> None:
        cache_dir = Path.home() / ".cache" / "commander-deck-builder"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = cache_dir / "color_identity_index.json"
        self.index = self._load_index()

    def get_color_identity(self, card_name: str) -> Optional[Set[str]]:
        key = card_name.strip().lower()
        cached = self.index.get(key)
        if isinstance(cached, list):
            return set(str(item).upper() for item in cached)
        identity = self._fetch_color_identity(card_name)
        if identity is None:
            return None
        self.index[key] = sorted(identity)
        self._save_index()
        return identity

    def _fetch_color_identity(self, card_name: str) -> Optional[Set[str]]:
        encoded = urllib.parse.quote(card_name, safe="")
        req = urllib.request.Request(
            f"https://api.scryfall.com/cards/named?exact={encoded}",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        values = payload.get("color_identity")
        if not isinstance(values, list):
            return None
        return set(str(item).upper() for item in values if isinstance(item, str))

    def _load_index(self) -> Dict[str, List[str]]:
        if not self.index_path.exists():
            return {}
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, List[str]] = {}
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, list):
                out[key] = [str(item).upper() for item in value if isinstance(item, str)]
        return out

    def _save_index(self) -> None:
        self.index_path.write_text(json.dumps(self.index, indent=2), encoding="utf-8")


def enforce_ai_commander_guardrails(
    collection: CollectionStore,
    deck: List[DeckCard],
    commander_input: str,
    color_cache: Optional[ColorIdentityCache] = None,
) -> List[DeckCard]:
    if color_cache is None:
        color_cache = ColorIdentityCache()
    commander_name = _resolve_commander_name(collection, commander_input)
    if not commander_name:
        raise RuntimeError("Commander must exist in collection for AI guardrails.")

    commander_colors = color_cache.get_color_identity(commander_name)
    if commander_colors is None:
        raise RuntimeError("Could not determine commander color identity from Scryfall.")

    used_counts: Dict[str, int] = {commander_name: 1}
    section_by_name = {card.name: card.section for card in deck}
    legal_cards: List[DeckCard] = [DeckCard(section="Commander", name=commander_name, quantity=1)]

    for card in deck:
        if card.name == commander_name:
            continue
        if card.name not in collection.cards:
            continue
        if not _is_color_legal(card.name, commander_colors, color_cache):
            continue
        available = collection.cards[card.name] - used_counts.get(card.name, 0)
        if available <= 0:
            continue
        max_allowed = available if card.name in BASIC_LANDS else min(1, available)
        qty = min(max(0, card.quantity), max_allowed)
        if qty <= 0:
            continue
        used_counts[card.name] = used_counts.get(card.name, 0) + qty
        section = _infer_section(card.name, section_by_name.get(card.name, card.section))
        legal_cards.append(DeckCard(section=section, name=card.name, quantity=qty))

    total = sum(card.quantity for card in legal_cards)
    if total < 100:
        _fill_with_legal_cards(
            collection=collection,
            legal_cards=legal_cards,
            used_counts=used_counts,
            commander_name=commander_name,
            commander_colors=commander_colors,
            section_by_name=section_by_name,
            color_cache=color_cache,
        )

    total = sum(card.quantity for card in legal_cards)
    if total != 100:
        raise RuntimeError(
            f"Guardrails could not build a legal 100-card commander deck from collection (got {total})."
        )
    return legal_cards


def _fill_with_legal_cards(
    collection: CollectionStore,
    legal_cards: List[DeckCard],
    used_counts: Dict[str, int],
    commander_name: str,
    commander_colors: Set[str],
    section_by_name: Dict[str, str],
    color_cache: ColorIdentityCache,
) -> None:
    basics_first = sorted([name for name in collection.cards if name in BASIC_LANDS])
    others = sorted([name for name in collection.cards if name not in BASIC_LANDS], key=lambda n: n.lower())
    candidates = basics_first + others
    total = sum(card.quantity for card in legal_cards)

    for name in candidates:
        if total >= 100:
            break
        if name == commander_name:
            continue
        if not _is_color_legal(name, commander_colors, color_cache):
            continue
        available = collection.cards[name] - used_counts.get(name, 0)
        if available <= 0:
            continue
        max_take = available if name in BASIC_LANDS else min(1, available)
        take = min(max_take, 100 - total)
        if take <= 0:
            continue
        used_counts[name] = used_counts.get(name, 0) + take
        section = _infer_section(name, section_by_name.get(name, "Nonland"))
        legal_cards.append(DeckCard(section=section, name=name, quantity=take))
        total += take


def _is_color_legal(card_name: str, commander_colors: Set[str], color_cache: ColorIdentityCache) -> bool:
    identity = color_cache.get_color_identity(card_name)
    if identity is None:
        return False
    return identity.issubset(commander_colors)


def _infer_section(card_name: str, existing_section: str) -> str:
    if existing_section:
        lowered = existing_section.strip().lower()
        if lowered == "land":
            return "Land"
        if lowered == "commander":
            return "Commander"
    if card_name in BASIC_LANDS:
        return "Land"
    lowered_name = card_name.lower()
    if any(token in lowered_name for token in LAND_HINTS):
        return "Land"
    return "Nonland"


def _resolve_commander_name(collection: CollectionStore, commander_input: str) -> Optional[str]:
    lowered = commander_input.strip().lower()
    for name in collection.cards.keys():
        if name.lower() == lowered:
            return name
    return None
