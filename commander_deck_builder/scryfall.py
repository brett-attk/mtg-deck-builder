import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


class ScryfallImageCache:
    def __init__(self, activity_callback: Callable[[str], None] | None = None) -> None:
        self.cache_dir = Path.home() / ".cache" / "commander-deck-builder"
        self.image_dir = self.cache_dir / "images"
        self.index_path = self.cache_dir / "image_index.json"
        self.meta_index_path = self.cache_dir / "card_meta_index.json"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.image_dir.mkdir(parents=True, exist_ok=True)

        self.lock = threading.Lock()
        self.index = self._load_index()
        self.meta_index = self._load_meta_index()
        self.last_request_ts = 0.0
        # Keep requests comfortably under Scryfall limits.
        self.min_request_interval_seconds = 0.20
        self.activity_callback = activity_callback

    def get_or_fetch(self, card_name: str) -> Optional[Path]:
        image_path, _exact_match = self.get_or_fetch_with_preference(card_name)
        return image_path

    def repair_cached_image(self, card_name: str, set_code: str = "", collector_number: str = "") -> None:
        normalized_name = card_name.strip().lower()
        normalized_set = set_code.strip().lower()
        normalized_collector = collector_number.strip().lower()
        keys = [
            self._cache_key(normalized_name, normalized_set, normalized_collector),
            normalized_name,
        ]
        paths_to_remove: set[str] = set()
        with self.lock:
            for key in keys:
                cached = self.index.pop(key, None)
                if isinstance(cached, dict):
                    path_value = cached.get("path")
                    if isinstance(path_value, str) and path_value:
                        paths_to_remove.add(path_value)
            for path_value in list(paths_to_remove):
                self._drop_entries_for_path_unlocked(path_value)
            self._save_index()
        for path_value in paths_to_remove:
            try:
                path = Path(path_value)
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        self._emit_activity(f"Scryfall cache repair: cleared cached image for '{card_name}'")

    def get_or_fetch_with_preference(
        self,
        card_name: str,
        set_code: str = "",
        collector_number: str = "",
    ) -> Tuple[Optional[Path], bool]:
        normalized_name = card_name.strip().lower()
        normalized_set = set_code.strip().lower()
        normalized_collector = collector_number.strip().lower()
        wants_specific_printing = bool(normalized_set and normalized_collector)

        cache_key = self._cache_key(normalized_name, normalized_set, normalized_collector)
        cached_path, cached_exact = self._get_cached_image(cache_key)
        if cached_path is not None:
            return cached_path, cached_exact
        if wants_specific_printing:
            # Always prefer any cached image before hitting Scryfall.
            generic_cached_path, _generic_cached_exact = self._get_cached_image(normalized_name)
            if generic_cached_path is not None:
                return generic_cached_path, False

        image_url: Optional[str] = None
        scryfall_id: Optional[str] = None
        exact_match = not wants_specific_printing

        if wants_specific_printing:
            print_data = self._fetch_with_retry(
                lambda: self._fetch_printing_data(normalized_set, normalized_collector)
            )
            if print_data is not None and self._card_name_matches(card_name, print_data.get("name", "")):
                image_url, scryfall_id = self._extract_image_info(print_data)
                exact_match = bool(image_url and scryfall_id)

        if not image_url or not scryfall_id:
            name_data = self._fetch_with_retry(lambda: self._fetch_card_data(card_name))
            if name_data is None:
                return None, exact_match
            image_url, scryfall_id = self._extract_image_info(name_data)
            if not image_url or not scryfall_id:
                return None, exact_match
            if wants_specific_printing:
                exact_match = False

        image_path = self.image_dir / f"{scryfall_id}.jpg"
        if not image_path.exists():
            self._emit_activity(f"Scryfall download: image for '{card_name}'")
            try:
                urllib.request.urlretrieve(image_url, image_path)  # noqa: S310
                self._emit_activity(f"Scryfall download complete: '{card_name}'")
            except Exception:
                self._emit_activity(f"Scryfall download failed: '{card_name}'")
                raise

        with self.lock:
            self.index[cache_key] = {
                "path": str(image_path),
                "id": scryfall_id,
                "exact_match": "true" if exact_match else "false",
            }
            # Keep the generic name cache warm as a fallback.
            if normalized_name not in self.index:
                self.index[normalized_name] = {
                    "path": str(image_path),
                    "id": scryfall_id,
                    "exact_match": "false" if wants_specific_printing else "true",
                }
            self._save_index()
        return image_path, exact_match

    def prefetch_missing_collection_images(
        self,
        cards: List[Tuple[str, Dict[str, str]]],
        max_to_fetch: int = 8,
    ) -> Tuple[int, int]:
        if max_to_fetch <= 0:
            return 0, 0

        candidates: List[Tuple[str, str, str]] = []
        seen: set[str] = set()
        for card_name, meta in cards:
            normalized_name = card_name.strip().lower()
            if not normalized_name:
                continue
            set_code = (meta.get("set_code") or "").strip().lower()
            collector_number = (meta.get("collector_number") or "").strip().lower()
            key = self._cache_key(normalized_name, set_code, collector_number)
            if key in seen:
                continue
            seen.add(key)
            if self._has_cached_image_for(normalized_name, set_code, collector_number):
                continue
            candidates.append((card_name, set_code, collector_number))

        fetched = 0
        attempts = min(len(candidates), max_to_fetch)
        for card_name, set_code, collector_number in candidates[:attempts]:
            try:
                image_path, _exact_match = self.get_or_fetch_with_preference(
                    card_name=card_name,
                    set_code=set_code,
                    collector_number=collector_number,
                )
                if image_path is not None:
                    fetched += 1
            except Exception:
                self._emit_activity(f"Scryfall prefetch skipped failed card: '{card_name}'")
                continue
        remaining = max(0, len(candidates) - attempts)
        return fetched, remaining

    def collection_image_cache_coverage(
        self,
        cards: List[Tuple[str, Dict[str, str]]],
    ) -> Tuple[int, int]:
        seen: set[str] = set()
        total = 0
        cached = 0
        for card_name, meta in cards:
            normalized_name = card_name.strip().lower()
            if not normalized_name:
                continue
            set_code = (meta.get("set_code") or "").strip().lower()
            collector_number = (meta.get("collector_number") or "").strip().lower()
            key = self._cache_key(normalized_name, set_code, collector_number)
            if key in seen:
                continue
            seen.add(key)
            total += 1
            if self._has_cached_image_for(normalized_name, set_code, collector_number):
                cached += 1
        return cached, total

    def _load_index(self) -> Dict[str, Dict[str, str]]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_index(self) -> None:
        self.index_path.write_text(json.dumps(self.index, indent=2), encoding="utf-8")

    def _load_meta_index(self) -> Dict[str, Dict[str, str]]:
        if not self.meta_index_path.exists():
            return {}
        try:
            return json.loads(self.meta_index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_meta_index(self) -> None:
        self.meta_index_path.write_text(json.dumps(self.meta_index, indent=2), encoding="utf-8")

    def get_card_type_category(self, card_name: str) -> str:
        key = card_name.strip().lower()
        with self.lock:
            cached = self.meta_index.get(key, {})
            type_line = (cached.get("type_line") or "").strip()
        if not type_line:
            type_line = self._fetch_and_cache_type_line(card_name)
        return self._to_category(type_line)

    def get_card_type_category_cached(self, card_name: str) -> Optional[str]:
        key = card_name.strip().lower()
        with self.lock:
            cached = self.meta_index.get(key, {})
            type_line = (cached.get("type_line") or "").strip()
        if not type_line:
            return None
        return self._to_category(type_line)

    def prefetch_missing_type_lines(
        self,
        card_names: List[str],
        max_to_fetch: int = 16,
    ) -> Tuple[int, int]:
        if max_to_fetch <= 0:
            return 0, 0

        normalized_names: List[str] = []
        seen: set[str] = set()
        for card_name in card_names:
            normalized = card_name.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_names.append(card_name)

        missing: List[str] = []
        for card_name in normalized_names:
            if self.get_card_type_category_cached(card_name) is None:
                missing.append(card_name)

        fetched = 0
        attempts = min(len(missing), max_to_fetch)
        for card_name in missing[:attempts]:
            type_line = self._fetch_and_cache_type_line(card_name)
            if type_line:
                fetched += 1

        remaining = max(0, len(missing) - attempts)
        return fetched, remaining

    def _fetch_and_cache_type_line(self, card_name: str) -> str:
        key = card_name.strip().lower()
        type_line = ""
        last_error: Optional[Exception] = None
        for attempt in range(4):
            try:
                data = self._fetch_card_data(card_name)
                type_line = (data.get("type_line") or "").strip()
                break
            except urllib.error.HTTPError as err:
                last_error = err
                if err.code != 429:
                    break
                time.sleep(self._retry_delay_from_headers(err, 1.25 + attempt * 0.5))
            except Exception as err:  # noqa: BLE001
                last_error = err
                break

        if type_line:
            with self.lock:
                existing = self.meta_index.get(key, {})
                existing["type_line"] = type_line
                self.meta_index[key] = existing
                self._save_meta_index()
        elif isinstance(last_error, urllib.error.HTTPError) and last_error.code == 404:
            with self.lock:
                existing = self.meta_index.get(key, {})
                existing["type_line"] = ""
                self.meta_index[key] = existing
                self._save_meta_index()
        return type_line

    def _fetch_card_data(self, card_name: str) -> Dict[str, object]:
        self._respect_rate_limit()
        encoded = urllib.parse.quote(card_name, safe="")
        req = urllib.request.Request(
            f"https://api.scryfall.com/cards/named?exact={encoded}",
            headers={"Accept": "application/json"},
        )
        self._emit_activity(f"Scryfall request: card named '{card_name}'")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            self._emit_activity(f"Scryfall request failed: card named '{card_name}'")
            raise
        self._emit_activity(f"Scryfall response: card named '{card_name}'")
        return data

    def _fetch_printing_data(self, set_code: str, collector_number: str) -> Dict[str, object]:
        self._respect_rate_limit()
        encoded_collector = urllib.parse.quote(collector_number, safe="")
        req = urllib.request.Request(
            f"https://api.scryfall.com/cards/{set_code}/{encoded_collector}",
            headers={"Accept": "application/json"},
        )
        self._emit_activity(f"Scryfall request: printing {set_code.upper()} #{collector_number}")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            self._emit_activity(f"Scryfall request failed: printing {set_code.upper()} #{collector_number}")
            raise
        self._emit_activity(f"Scryfall response: printing {set_code.upper()} #{collector_number}")
        return data

    def _to_category(self, type_line: str) -> str:
        lowered = type_line.lower()
        if "creature" in lowered:
            return "Creature"
        if "artifact" in lowered:
            return "Artifact"
        if "enchantment" in lowered:
            return "Enchantment"
        if "instant" in lowered:
            return "Instant"
        if "sorcery" in lowered:
            return "Sorcery"
        if "land" in lowered:
            return "Land"
        return "Other"

    def _respect_rate_limit(self) -> None:
        with self.lock:
            now = time.monotonic()
            wait_for = self.min_request_interval_seconds - (now - self.last_request_ts)
            if wait_for > 0:
                time.sleep(wait_for)
            self.last_request_ts = time.monotonic()

    def _retry_delay_from_headers(self, err: urllib.error.HTTPError, default_delay: float) -> float:
        raw = err.headers.get("Retry-After") if err.headers else None
        if not raw:
            return default_delay
        try:
            return max(0.2, float(raw))
        except ValueError:
            return default_delay

    def _fetch_with_retry(self, fetcher) -> Optional[Dict[str, object]]:
        for attempt in range(4):
            try:
                return fetcher()
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    return None
                if err.code != 429:
                    return None
                delay = self._retry_delay_from_headers(err, 1.25 + attempt * 0.5)
                self._emit_activity(f"Scryfall rate limit hit, retrying in {delay:.1f}s")
                time.sleep(delay)
            except Exception:
                return None
        return None

    def _extract_image_info(self, data: Dict[str, object]) -> Tuple[Optional[str], Optional[str]]:
        scryfall_id = data.get("id")
        image_uris = data.get("image_uris")
        if isinstance(image_uris, dict):
            return image_uris.get("normal"), scryfall_id
        faces = data.get("card_faces", [])
        if isinstance(faces, list) and faces:
            first_face = faces[0]
            if isinstance(first_face, dict):
                face_images = first_face.get("image_uris") or {}
                if isinstance(face_images, dict):
                    return face_images.get("normal"), scryfall_id
        return None, None

    def _cache_key(self, card_name: str, set_code: str, collector_number: str) -> str:
        if set_code and collector_number:
            return f"{card_name}|{set_code}|{collector_number}"
        return card_name

    def _has_cached_image_for(self, card_name: str, set_code: str, collector_number: str) -> bool:
        cache_key = self._cache_key(card_name, set_code, collector_number)
        cached_path, _cached_exact = self._get_cached_image(cache_key)
        if cached_path is not None:
            return True
        if set_code and collector_number:
            # Accept generic-name cache as fallback for specific printings.
            generic_path, _generic_exact = self._get_cached_image(card_name)
            if generic_path is not None:
                return True
        return False

    def _get_cached_image(self, cache_key: str) -> Tuple[Optional[Path], bool]:
        with self.lock:
            cached = self.index.get(cache_key, {})
            image_value = cached.get("path")
            exact = cached.get("exact_match", "true") != "false"
        if image_value:
            image_path = Path(image_value)
            if image_path.exists():
                return image_path, exact
        return None, exact

    def _card_name_matches(self, expected_name: str, returned_name: str) -> bool:
        return expected_name.strip().lower() == returned_name.strip().lower()

    def _drop_entries_for_path_unlocked(self, path_value: str) -> None:
        keys_to_drop = []
        for key, value in self.index.items():
            if isinstance(value, dict) and value.get("path") == path_value:
                keys_to_drop.append(key)
        for key in keys_to_drop:
            self.index.pop(key, None)

    def _emit_activity(self, message: str) -> None:
        if self.activity_callback is None:
            return
        try:
            self.activity_callback(message)
        except Exception:
            return
