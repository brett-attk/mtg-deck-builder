from dataclasses import dataclass


@dataclass
class DeckCard:
    section: str
    name: str
    quantity: int
