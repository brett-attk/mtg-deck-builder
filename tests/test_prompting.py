import unittest

from commander_deck_builder.collection import CollectionStore
from commander_deck_builder.prompting import build_deck_prompt


class TestPrompting(unittest.TestCase):
    def test_prompt_uses_commander_input_value(self):
        collection = CollectionStore()
        collection.cards = {
            "Fynn, the Fangbearer": 1,
            "Forest": 20,
        }
        collection.card_meta = {}

        commander_input = "Fynn, the Fangbearer"
        prompt = build_deck_prompt(
            collection=collection,
            commander=commander_input,
            theme="Poison counters",
            bracket_target="3",
            extra_prompt="Aggressive curve",
        )

        self.assertIn(f"Commander: {commander_input}", prompt)


if __name__ == "__main__":
    unittest.main()
