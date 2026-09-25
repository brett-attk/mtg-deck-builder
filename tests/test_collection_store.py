import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from commander_deck_builder.collection import CollectionStore


class TestCollectionStore(unittest.TestCase):
    def _build_store(self, tmp_home: str) -> CollectionStore:
        with patch("commander_deck_builder.collection.Path.home", return_value=Path(tmp_home)):
            return CollectionStore()

    def test_load_parses_quantity_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp_home:
            path = Path(tmp) / "collection.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Name", "Set code", "Set name", "Collector number", "Foil", "Rarity", "Quantity"])
                writer.writerow(["Fynn, the Fangbearer", "fdn", "Foundations", "637", "normal", "uncommon", "1"])
                writer.writerow(["Fynn, the Fangbearer", "fdn", "Foundations", "637", "normal", "uncommon", "2"])
                writer.writerow(["Forest", "one", "Phyrexia: All Will Be One", "271", "foil", "common", "3"])

            store = self._build_store(tmp_home)
            store.load(path)

            self.assertEqual(store.cards["Fynn, the Fangbearer"], 3)
            self.assertEqual(store.cards["Forest"], 3)
            meta = store.card_meta["Fynn, the Fangbearer"]
            self.assertEqual(meta["set_code"], "fdn")
            self.assertEqual(meta["collector_number"], "637")
            self.assertEqual(meta["foil"], "normal")
            self.assertEqual(meta["rarity"], "uncommon")

    def test_load_reuses_cached_nosql_store_when_csv_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp_home:
            path = Path(tmp) / "collection.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Name", "Set code", "Set name", "Collector number", "Foil", "Rarity", "Quantity"])
                writer.writerow(["Arcane Signet", "cmm", "Commander Masters", "371", "normal", "common", "1"])

            first_store = self._build_store(tmp_home)
            first_store.load(path)
            self.assertEqual(first_store.cards["Arcane Signet"], 1)

            second_store = self._build_store(tmp_home)
            with patch("commander_deck_builder.collection.csv.DictReader", side_effect=AssertionError("parsed csv")):
                second_store.load(path)
            self.assertEqual(second_store.cards["Arcane Signet"], 1)

    def test_load_active_collection_reads_imported_datastore_without_csv(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp_home:
            path = Path(tmp) / "collection.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Name", "Set code", "Set name", "Collector number", "Foil", "Rarity", "Quantity"])
                writer.writerow(["Forest", "one", "Phyrexia: All Will Be One", "271", "foil", "common", "3"])

            first_store = self._build_store(tmp_home)
            first_store.import_csv(path)
            path.unlink()

            second_store = self._build_store(tmp_home)
            self.assertTrue(second_store.load_active_collection())
            self.assertEqual(second_store.cards["Forest"], 3)
            self.assertEqual(second_store.source_label, "collection.csv")

    def test_load_prefers_datastore_when_csv_deleted(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp_home:
            path = Path(tmp) / "collection.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Name", "Set code", "Set name", "Collector number", "Foil", "Rarity", "Quantity"])
                writer.writerow(["Sol Ring", "cmm", "Commander Masters", "395", "normal", "uncommon", "2"])

            first_store = self._build_store(tmp_home)
            first_store.import_csv(path)
            path.unlink()

            second_store = self._build_store(tmp_home)
            second_store.load(path)
            self.assertEqual(second_store.cards["Sol Ring"], 2)


if __name__ == "__main__":
    unittest.main()
