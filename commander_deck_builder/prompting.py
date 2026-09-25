import csv
import io
from typing import List

from .collection import CollectionStore
from .models import DeckCard


def build_deck_prompt(
    collection: CollectionStore,
    commander: str,
    theme: str,
    bracket_target: str,
    extra_prompt: str,
) -> str:
    collection_text = "\n".join(collection.as_prompt_rows())
    return (
        "Build a 100-card Magic: The Gathering Commander deck from this collection.\n"
        f"Commander: {commander}\n"
        f"Theme: {theme}\n"
        f"Power target: bracket {bracket_target}\n"
        "Rules:\n"
        "- This is always MTG and always the Commander format\n"
        "- Use only cards in the supplied collection list\n"
        "- Commander color identity is strict: every included card must be colorless or fully within the commander's color identity\n"
        "- Respect singleton rules (except basic lands)\n"
        "- Output exactly CSV with header: Section,Name,Quantity\n"
        "- Include Commander section and exactly 100 total cards\n"
        "- Do not output markdown\n"
        f"- Extra user preferences: {extra_prompt or 'None'}\n\n"
        "Collection cards (Name,Quantity):\n"
        f"{collection_text}"
    )


def parse_deck_csv(text: str) -> List[DeckCard]:
    normalized = text.strip()
    if "```" in normalized:
        normalized = normalized.replace("```csv", "").replace("```", "").strip()

    rows = list(csv.DictReader(io.StringIO(normalized)))
    if not rows:
        raise RuntimeError("Model response did not include CSV rows.")

    deck: List[DeckCard] = []
    for row in rows:
        section = (row.get("Section") or "").strip() or "Nonland"
        name = (row.get("Name") or "").strip().strip('"')
        if not name:
            continue
        try:
            quantity = int((row.get("Quantity") or "1").strip())
        except ValueError:
            quantity = 1
        deck.append(DeckCard(section=section, name=name, quantity=quantity))

    card_total = sum(card.quantity for card in deck)
    if card_total != 100:
        raise RuntimeError(f"Model returned {card_total} cards, expected 100.")
    return deck
