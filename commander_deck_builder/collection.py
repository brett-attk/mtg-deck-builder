import csv
import hashlib
import shelve
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class CollectionStore:
    def __init__(self) -> None:
        self.path: Optional[Path] = None
        self.source_label: str = ""
        self.cards: Dict[str, int] = {}
        self.card_meta: Dict[str, Dict[str, str]] = {}
        self._display_rows_cache: List[Tuple[str, int, Dict[str, str]]] = []
        self._prompt_rows_cache: List[str] = []
        self._cache_dir = Path.home() / ".cache" / "commander-deck-builder"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = str(self._cache_dir / "collection_store")
        self._collections_key = "collections"
        self._active_collection_id_key = "active_collection_id"
        self._path_index_key = "path_index"

    def load(self, csv_path: Path) -> None:
        csv_path = csv_path.resolve()
        collection_id = self._collection_id_for_path(csv_path)
        if not csv_path.exists():
            if self._try_load_collection_by_id(collection_id):
                return
            raise FileNotFoundError(f"Collection file not found: {csv_path}")

        fingerprint = self._build_fingerprint(csv_path)
        if self._try_load_cached_for_path(collection_id, csv_path, fingerprint):
            return
        self._import_csv_into_collection(csv_path, collection_id, fingerprint)

    def import_csv(self, csv_path: Path) -> None:
        csv_path = csv_path.resolve()
        if not csv_path.exists():
            raise FileNotFoundError(f"Collection file not found: {csv_path}")
        collection_id = self._collection_id_for_path(csv_path)
        fingerprint = self._build_fingerprint(csv_path)
        self._import_csv_into_collection(csv_path, collection_id, fingerprint)

    def load_active_collection(self) -> bool:
        try:
            with shelve.open(self._db_path) as db:
                active_id = str(db.get(self._active_collection_id_key, "")).strip()
                collections = db.get(self._collections_key, {})
                if not active_id or not isinstance(collections, dict):
                    return False
                raw_doc = collections.get(active_id)
                if not isinstance(raw_doc, dict):
                    return False
                self._apply_doc(raw_doc)
                return True
        except Exception:
            return False

    def has_active_collection(self) -> bool:
        try:
            with shelve.open(self._db_path) as db:
                active_id = str(db.get(self._active_collection_id_key, "")).strip()
                collections = db.get(self._collections_key, {})
                return bool(active_id and isinstance(collections, dict) and active_id in collections)
        except Exception:
            return False

    def as_prompt_rows(self) -> List[str]:
        return list(self._prompt_rows_cache)

    def as_display_rows(self) -> List[Tuple[str, int, Dict[str, str]]]:
        return [(name, qty, dict(meta)) for name, qty, meta in self._display_rows_cache]

    def _import_csv_into_collection(self, csv_path: Path, collection_id: str, fingerprint: str) -> None:
        cards: Dict[str, int] = {}
        card_meta: Dict[str, Dict[str, str]] = {}
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                name = (row.get("Name") or "").strip().strip('"')
                if not name:
                    continue
                try:
                    quantity = int((row.get("Quantity") or "1").strip())
                except ValueError:
                    quantity = 1
                cards[name] = cards.get(name, 0) + quantity
                if name not in card_meta:
                    card_meta[name] = {
                        "set_code": (row.get("Set code") or "").strip(),
                        "set_name": (row.get("Set name") or "").strip(),
                        "collector_number": (row.get("Collector number") or "").strip(),
                        "foil": (row.get("Foil") or "").strip(),
                        "rarity": (row.get("Rarity") or "").strip(),
                    }

        display_rows = self._build_display_rows(cards, card_meta)
        prompt_rows = self._build_prompt_rows(cards)
        doc = {
            "collection_id": collection_id,
            "source_path": str(csv_path),
            "source_name": csv_path.name,
            "source_fingerprint": fingerprint,
            "cards": dict(cards),
            "card_meta": {name: dict(meta) for name, meta in card_meta.items()},
            "display_rows": [(name, qty, dict(meta)) for name, qty, meta in display_rows],
            "prompt_rows": list(prompt_rows),
            "imported_at": int(time.time()),
        }
        self._save_doc(collection_id, doc)
        self._apply_doc(doc)

    def _build_display_rows(
        self,
        cards: Dict[str, int],
        card_meta: Dict[str, Dict[str, str]],
    ) -> List[Tuple[str, int, Dict[str, str]]]:
        rows: List[Tuple[str, int, Dict[str, str]]] = []
        for name, qty in sorted(cards.items(), key=lambda item: item[0].lower()):
            rows.append((name, qty, dict(card_meta.get(name, {}))))
        return rows

    def _build_prompt_rows(self, cards: Dict[str, int]) -> List[str]:
        return [f"{name},{qty}" for name, qty in sorted(cards.items(), key=lambda item: item[0].lower())]

    def _build_fingerprint(self, csv_path: Path) -> str:
        stat = csv_path.stat()
        return f"{csv_path}:{stat.st_size}:{stat.st_mtime_ns}"

    def _collection_id_for_path(self, csv_path: Path) -> str:
        key = str(csv_path).encode("utf-8")
        return hashlib.sha1(key).hexdigest()  # noqa: S324

    def _try_load_cached_for_path(self, collection_id: str, csv_path: Path, fingerprint: str) -> bool:
        try:
            with shelve.open(self._db_path) as db:
                collections = db.get(self._collections_key, {})
                if not isinstance(collections, dict):
                    return False
                raw_doc = collections.get(collection_id)
                if not isinstance(raw_doc, dict):
                    return False
                if str(raw_doc.get("source_path", "")) != str(csv_path):
                    return False
                if str(raw_doc.get("source_fingerprint", "")) != fingerprint:
                    return False
                self._set_active_collection_id(collection_id, db)
                self._apply_doc(raw_doc)
                return True
        except Exception:
            return False

    def _try_load_collection_by_id(self, collection_id: str) -> bool:
        try:
            with shelve.open(self._db_path) as db:
                collections = db.get(self._collections_key, {})
                if not isinstance(collections, dict):
                    return False
                raw_doc = collections.get(collection_id)
                if not isinstance(raw_doc, dict):
                    return False
                self._set_active_collection_id(collection_id, db)
                self._apply_doc(raw_doc)
                return True
        except Exception:
            return False

    def _save_doc(self, collection_id: str, doc: Dict[str, object]) -> None:
        try:
            with shelve.open(self._db_path, writeback=True) as db:
                collections = db.get(self._collections_key, {})
                if not isinstance(collections, dict):
                    collections = {}
                collections[collection_id] = doc
                db[self._collections_key] = collections
                path_index = db.get(self._path_index_key, {})
                if not isinstance(path_index, dict):
                    path_index = {}
                source_path = str(doc.get("source_path", ""))
                if source_path:
                    path_index[source_path] = collection_id
                db[self._path_index_key] = path_index
                self._set_active_collection_id(collection_id, db)
        except Exception:
            return

    def _set_active_collection_id(self, collection_id: str, db: shelve.Shelf) -> None:
        db[self._active_collection_id_key] = collection_id

    def _apply_doc(self, doc: Dict[str, object]) -> None:
        source_path = str(doc.get("source_path", "")).strip()
        self.path = Path(source_path) if source_path else None
        source_name = str(doc.get("source_name", "")).strip()
        if source_name:
            self.source_label = source_name
        elif self.path is not None:
            self.source_label = self.path.name
        else:
            self.source_label = "datastore"

        cards = doc.get("cards", {})
        card_meta = doc.get("card_meta", {})
        display_rows = doc.get("display_rows", [])
        prompt_rows = doc.get("prompt_rows", [])

        if isinstance(cards, dict):
            self.cards = {str(name): int(qty) for name, qty in cards.items()}
        else:
            self.cards = {}
        if isinstance(card_meta, dict):
            self.card_meta = {
                str(name): dict(meta) if isinstance(meta, dict) else {}
                for name, meta in card_meta.items()
            }
        else:
            self.card_meta = {}

        parsed_rows: List[Tuple[str, int, Dict[str, str]]] = []
        if isinstance(display_rows, list):
            for row in display_rows:
                if not isinstance(row, (list, tuple)) or len(row) != 3:
                    continue
                name, qty, meta = row
                if not isinstance(name, str):
                    continue
                parsed_rows.append((name, int(qty), dict(meta) if isinstance(meta, dict) else {}))
        self._display_rows_cache = parsed_rows if parsed_rows else self._build_display_rows(self.cards, self.card_meta)

        if isinstance(prompt_rows, list):
            self._prompt_rows_cache = [str(row) for row in prompt_rows]
        else:
            self._prompt_rows_cache = self._build_prompt_rows(self.cards)
