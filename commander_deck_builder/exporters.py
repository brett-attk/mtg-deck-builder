import csv
import io
from typing import Dict, List

from .models import DeckCard


def format_quantity_name_set_lines(cards: List[DeckCard], card_meta: Dict[str, Dict[str, str]]) -> str:
    rows: List[str] = []
    for card in cards:
        set_code = card_meta.get(card.name, {}).get("set_code", "").strip().upper()
        if set_code:
            rows.append(f"{card.quantity} {card.name} ({set_code})")
        else:
            rows.append(f"{card.quantity} {card.name}")
    return "\n".join(rows)


def format_moxfield_lines(cards: List[DeckCard], card_meta: Dict[str, Dict[str, str]]) -> str:
    rows: List[str] = []
    for card in cards:
        set_code = card_meta.get(card.name, {}).get("set_code", "").strip().upper()
        if set_code:
            rows.append(f"{card.quantity} {card.name} ({set_code})")
        else:
            rows.append(f"{card.quantity} {card.name}")
    return "\n".join(rows)


def format_archidekt_lines(cards: List[DeckCard], card_meta: Dict[str, Dict[str, str]]) -> str:
    rows: List[str] = []
    for card in cards:
        set_code = card_meta.get(card.name, {}).get("set_code", "").strip().upper()
        if set_code:
            rows.append(f"{card.quantity} {card.name} [{set_code}]")
        else:
            rows.append(f"{card.quantity} {card.name}")
    return "\n".join(rows)


def format_standard_csv(cards: List[DeckCard]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Section", "Name", "Quantity"])
    for card in cards:
        writer.writerow([card.section, card.name, card.quantity])
    return output.getvalue()
