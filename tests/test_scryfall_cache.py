import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from commander_deck_builder.scryfall import ScryfallImageCache


class TestScryfallImageCache(unittest.TestCase):
    def _build_cache(self, tmp_home: str) -> ScryfallImageCache:
        with patch("commander_deck_builder.scryfall.Path.home", return_value=Path(tmp_home)):
            return ScryfallImageCache()

    def test_prefers_set_and_collector_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            printing_data = {
                "id": "print-1",
                "name": "Fynn, the Fangbearer",
                "image_uris": {"normal": "https://img/print-1.jpg"},
            }

            with patch.object(cache, "_fetch_with_retry", return_value=printing_data) as mock_fetch:
                with patch("commander_deck_builder.scryfall.urllib.request.urlretrieve") as mock_dl:
                    mock_dl.side_effect = lambda _url, path: Path(path).write_bytes(b"x")
                    image_path, exact = cache.get_or_fetch_with_preference(
                        card_name="Fynn, the Fangbearer",
                        set_code="fdn",
                        collector_number="637",
                    )

            self.assertTrue(exact)
            self.assertIsNotNone(image_path)
            self.assertTrue(image_path.exists())
            self.assertGreaterEqual(mock_fetch.call_count, 1)

    def test_falls_back_to_name_when_printing_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            name_data = {
                "id": "name-1",
                "name": "Fynn, the Fangbearer",
                "image_uris": {"normal": "https://img/name-1.jpg"},
            }

            with patch.object(cache, "_fetch_with_retry", side_effect=[None, name_data]):
                with patch("commander_deck_builder.scryfall.urllib.request.urlretrieve") as mock_dl:
                    mock_dl.side_effect = lambda _url, path: Path(path).write_bytes(b"x")
                    image_path, exact = cache.get_or_fetch_with_preference(
                        card_name="Fynn, the Fangbearer",
                        set_code="fdn",
                        collector_number="637",
                    )

            self.assertFalse(exact)
            self.assertIsNotNone(image_path)
            self.assertTrue(image_path.exists())

    def test_name_only_lookup_marks_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            name_data = {
                "id": "name-2",
                "name": "Arcane Signet",
                "image_uris": {"normal": "https://img/name-2.jpg"},
            }

            with patch.object(cache, "_fetch_with_retry", return_value=name_data):
                with patch("commander_deck_builder.scryfall.urllib.request.urlretrieve") as mock_dl:
                    mock_dl.side_effect = lambda _url, path: Path(path).write_bytes(b"x")
                    image_path, exact = cache.get_or_fetch_with_preference(
                        card_name="Arcane Signet",
                    )

            self.assertTrue(exact)
            self.assertIsNotNone(image_path)
            self.assertTrue(image_path.exists())

    def test_prefers_generic_cache_before_network_for_print_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            cached_file = cache.image_dir / "cached-generic.jpg"
            cached_file.write_bytes(b"x")
            cache.index["arcane signet"] = {
                "path": str(cached_file),
                "id": "cached-generic",
                "exact_match": "true",
            }
            cache._save_index()

            with patch.object(cache, "_fetch_with_retry") as mock_fetch:
                image_path, exact = cache.get_or_fetch_with_preference(
                    card_name="Arcane Signet",
                    set_code="fdn",
                    collector_number="637",
                )

            mock_fetch.assert_not_called()
            self.assertIsNotNone(image_path)
            self.assertEqual(image_path, cached_file)
            self.assertFalse(exact)

    def test_repair_cached_image_removes_bad_file_and_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            bad_file = cache.image_dir / "broken.jpg"
            bad_file.write_bytes(b"bad")
            cache.index["arcane signet"] = {
                "path": str(bad_file),
                "id": "broken",
                "exact_match": "true",
            }
            cache.index["arcane signet|fdn|637"] = {
                "path": str(bad_file),
                "id": "broken",
                "exact_match": "false",
            }
            cache._save_index()

            cache.repair_cached_image("Arcane Signet", set_code="fdn", collector_number="637")

            self.assertFalse(bad_file.exists())
            self.assertNotIn("arcane signet", cache.index)
            self.assertNotIn("arcane signet|fdn|637", cache.index)

    def test_prefetch_missing_collection_images_skips_cached_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            cached_file = cache.image_dir / "cached.jpg"
            cached_file.write_bytes(b"x")
            cache.index["arcane signet"] = {
                "path": str(cached_file),
                "id": "cached",
                "exact_match": "true",
            }
            cache._save_index()

            cards = [
                ("Arcane Signet", {"set_code": "", "collector_number": ""}),
                ("Sol Ring", {"set_code": "", "collector_number": ""}),
            ]
            with patch.object(
                cache,
                "get_or_fetch_with_preference",
                return_value=(cache.image_dir / "new.jpg", True),
            ) as mock_fetch:
                fetched, remaining = cache.prefetch_missing_collection_images(cards, max_to_fetch=8)

            self.assertEqual(fetched, 1)
            self.assertEqual(remaining, 0)
            mock_fetch.assert_called_once_with(
                card_name="Sol Ring",
                set_code="",
                collector_number="",
            )

    def test_prefetch_missing_collection_images_respects_max_to_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            cards = [
                ("Arcane Signet", {"set_code": "", "collector_number": ""}),
                ("Sol Ring", {"set_code": "", "collector_number": ""}),
                ("Forest", {"set_code": "", "collector_number": ""}),
            ]
            with patch.object(
                cache,
                "get_or_fetch_with_preference",
                return_value=(cache.image_dir / "new.jpg", True),
            ) as mock_fetch:
                fetched, remaining = cache.prefetch_missing_collection_images(cards, max_to_fetch=2)

            self.assertEqual(fetched, 2)
            self.assertEqual(remaining, 1)
            self.assertEqual(mock_fetch.call_count, 2)

    def test_prefetch_missing_collection_images_continues_after_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            cards = [
                ("Arcane Signet", {"set_code": "", "collector_number": ""}),
                ("Sol Ring", {"set_code": "", "collector_number": ""}),
            ]
            with patch.object(
                cache,
                "get_or_fetch_with_preference",
                side_effect=[RuntimeError("network"), (cache.image_dir / "ok.jpg", True)],
            ) as mock_fetch:
                fetched, remaining = cache.prefetch_missing_collection_images(cards, max_to_fetch=2)

            self.assertEqual(fetched, 1)
            self.assertEqual(remaining, 0)
            self.assertEqual(mock_fetch.call_count, 2)

    def test_collection_image_cache_coverage_counts_cached_and_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            cached_file = cache.image_dir / "cached.jpg"
            cached_file.write_bytes(b"x")
            cache.index["arcane signet"] = {
                "path": str(cached_file),
                "id": "cached-generic",
                "exact_match": "true",
            }
            cache._save_index()

            cards = [
                ("Arcane Signet", {"set_code": "", "collector_number": ""}),
                ("Sol Ring", {"set_code": "", "collector_number": ""}),
            ]
            cached, total = cache.collection_image_cache_coverage(cards)
            self.assertEqual(cached, 1)
            self.assertEqual(total, 2)

    def test_get_card_type_category_cached_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            self.assertIsNone(cache.get_card_type_category_cached("Arcane Signet"))

    def test_prefetch_missing_type_lines_respects_batch_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._build_cache(tmp)
            with patch.object(
                cache,
                "_fetch_and_cache_type_line",
                side_effect=["Artifact", "Creature", "Land"],
            ) as mock_fetch:
                fetched, remaining = cache.prefetch_missing_type_lines(
                    card_names=["Arcane Signet", "Llanowar Elves", "Forest"],
                    max_to_fetch=2,
                )

            self.assertEqual(fetched, 2)
            self.assertEqual(remaining, 1)
            self.assertEqual(mock_fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
