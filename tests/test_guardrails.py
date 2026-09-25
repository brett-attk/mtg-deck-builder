import unittest

from commander_deck_builder.collection import CollectionStore
from commander_deck_builder.guardrails import ColorIdentityCache, enforce_ai_commander_guardrails
from commander_deck_builder.models import DeckCard


class _FakeColorCache(ColorIdentityCache):
    def __init__(self, identities):
        self._identities = identities

    def get_color_identity(self, card_name: str):
        return self._identities.get(card_name)


class TestAiCommanderGuardrails(unittest.TestCase):
    def test_filters_off_color_cards_and_keeps_100(self):
        collection = CollectionStore()
        collection.cards = {
            "Fynn, the Fangbearer": 1,
            "Forest": 98,
            "Blight Mamba": 1,
            "Counterspell": 1,
        }
        collection.card_meta = {}

        identities = {
            "Fynn, the Fangbearer": {"G"},
            "Forest": set(),
            "Blight Mamba": {"G"},
            "Counterspell": {"U"},
        }
        cache = _FakeColorCache(identities)
        ai_deck = [
            DeckCard(section="Commander", name="Fynn, the Fangbearer", quantity=1),
            DeckCard(section="Nonland", name="Blight Mamba", quantity=1),
            DeckCard(section="Nonland", name="Counterspell", quantity=1),
            DeckCard(section="Land", name="Forest", quantity=97),
        ]

        fixed = enforce_ai_commander_guardrails(collection, ai_deck, "Fynn, the Fangbearer", cache)
        total = sum(card.quantity for card in fixed)
        self.assertEqual(total, 100)
        names = {card.name for card in fixed}
        self.assertNotIn("Counterspell", names)
        self.assertIn("Blight Mamba", names)

    def test_requires_commander_in_collection(self):
        collection = CollectionStore()
        collection.cards = {"Forest": 100}
        collection.card_meta = {}
        cache = _FakeColorCache({"Forest": set()})
        with self.assertRaises(RuntimeError):
            enforce_ai_commander_guardrails(collection, [], "Fynn, the Fangbearer", cache)


if __name__ == "__main__":
    unittest.main()
