import tempfile
import unittest
from pathlib import Path

from commander_deck_builder.deck_naming import choose_generated_deck_path, sanitize_deck_name


class TestDeckNaming(unittest.TestCase):
    def test_sanitize_deck_name(self):
        self.assertEqual(sanitize_deck_name("  Fynn Poison Bracket 3  "), "Fynn_Poison_Bracket_3")
        self.assertEqual(sanitize_deck_name("???"), "generated_deck")
        self.assertEqual(sanitize_deck_name("Atraxa, Infect!"), "Atraxa_Infect")

    def test_choose_generated_deck_path_uses_unique_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            first = choose_generated_deck_path(out_dir, "Fynn Poison")
            self.assertEqual(first.name, "Fynn_Poison.csv")
            first.write_text("x", encoding="utf-8")

            second = choose_generated_deck_path(out_dir, "Fynn Poison")
            self.assertEqual(second.name, "Fynn_Poison_2.csv")


if __name__ == "__main__":
    unittest.main()
