import unittest

from commander_deck_builder.exporters import format_quantity_name_set_lines
from commander_deck_builder.models import DeckCard


class TestExporters(unittest.TestCase):
    def test_formats_quantity_name_set_lines(self):
        cards = [
            DeckCard(section="Commander", name="Fynn, the Fangbearer", quantity=1),
            DeckCard(section="Land", name="Forest", quantity=4),
            DeckCard(section="Nonland", name="Arcane Signet", quantity=1),
        ]
        meta = {
            "Fynn, the Fangbearer": {"set_code": "fdn"},
            "Forest": {"set_code": "one"},
        }

        text = format_quantity_name_set_lines(cards, meta)
        lines = text.splitlines()

        self.assertEqual(lines[0], "1 Fynn, the Fangbearer (FDN)")
        self.assertEqual(lines[1], "4 Forest (ONE)")
        self.assertEqual(lines[2], "1 Arcane Signet")


if __name__ == "__main__":
    unittest.main()
