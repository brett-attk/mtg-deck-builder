import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from .collection import CollectionStore
from .guardrails import enforce_ai_commander_guardrails
from .models import DeckCard
from .prompting import build_deck_prompt, parse_deck_csv

try:
    from cursor_sdk import Agent, AgentOptions, Bridge, Client, LocalAgentOptions, SendOptions

    HAS_CURSOR_SDK = True
except Exception:
    # If app is launched outside the project venv, try importing cursor-sdk from ./venv.
    project_root = Path(__file__).resolve().parents[1]
    venv_lib_dir = project_root / ".venv" / "lib"
    if venv_lib_dir.exists():
        for py_dir in sorted(venv_lib_dir.glob("python*/site-packages")):
            site_path = str(py_dir)
            if site_path not in sys.path:
                sys.path.append(site_path)
    try:
        from cursor_sdk import Agent, AgentOptions, Bridge, Client, LocalAgentOptions, SendOptions

        HAS_CURSOR_SDK = True
    except Exception:
        Agent = None
        AgentOptions = None
        Bridge = None
        Client = None
        LocalAgentOptions = None
        SendOptions = None
        HAS_CURSOR_SDK = False


class FrontierDeckClient:
    provider_label = "OpenAI-compatible API"

    def __init__(self) -> None:
        self.base_url = os.getenv("FRONTIER_API_BASE", "https://api.openai.com/v1").rstrip("/")

    def build_deck(
        self,
        collection: CollectionStore,
        commander: str,
        theme: str,
        bracket_target: str,
        extra_prompt: str,
        api_key: str,
        model: str,
        status_callback: Callable[[str], None] | None = None,
    ) -> List[DeckCard]:
        if status_callback is not None:
            status_callback("Preparing OpenAI-compatible deck request...")
        if not api_key:
            raise RuntimeError("Missing FRONTIER_API_KEY (or OPENAI_API_KEY) in environment.")
        if not collection.cards:
            raise RuntimeError("Import and load a collection first.")

        user_prompt = build_deck_prompt(collection, commander, theme, bracket_target, extra_prompt)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert MTG Commander deck builder that follows strict CSV output rules.",
                },
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.5,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        if status_callback is not None:
            status_callback("Waiting for model response...")
        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        if status_callback is not None:
            status_callback("Model response received. Parsing deck list...")
        deck = parse_deck_csv(data["choices"][0]["message"]["content"])
        if status_callback is not None:
            status_callback("Applying MTG Commander guardrails...")
        return enforce_ai_commander_guardrails(collection, deck, commander)

    def test_connection(self, api_key: str, model: str) -> str:
        if not api_key:
            raise RuntimeError("Missing FRONTIER_API_KEY (or OPENAI_API_KEY).")
        if not model:
            raise RuntimeError("Missing model for OpenAI-compatible provider.")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Reply with OK only."},
                {"role": "user", "content": "OK"},
            ],
            "temperature": 0,
            "max_tokens": 8,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {err.code}: {detail[:220]}") from err
        except Exception as err:
            raise RuntimeError(f"Request failed: {err}") from err

        _ = data["choices"][0]["message"]["content"]
        return f"Connected to OpenAI-compatible API with model '{model}'."

    def list_models(self, api_key: str) -> List[str]:
        if not api_key:
            raise RuntimeError("Missing FRONTIER_API_KEY (or OPENAI_API_KEY).")
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {err.code}: {detail[:220]}") from err
        except Exception as err:
            raise RuntimeError(f"Request failed: {err}") from err

        items = data.get("data", [])
        if not isinstance(items, list):
            raise RuntimeError("Unexpected /models response format.")

        model_names: List[str] = []
        for item in items:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    model_names.append(model_id.strip())
        if not model_names:
            raise RuntimeError("No models returned by provider.")
        return sorted(set(model_names))


class CursorSdkDeckClient:
    provider_label = "Cursor SDK"

    def build_deck(
        self,
        collection: CollectionStore,
        commander: str,
        theme: str,
        bracket_target: str,
        extra_prompt: str,
        api_key: str,
        model: str,
        status_callback: Callable[[str], None] | None = None,
    ) -> List[DeckCard]:
        def emit(message: str) -> None:
            if status_callback is not None:
                status_callback(message)

        if not HAS_CURSOR_SDK:
            raise RuntimeError("cursor-sdk is not installed. Install dependencies first.")
        if not api_key:
            raise RuntimeError("Missing CURSOR_API_KEY in environment.")
        if not collection.cards:
            raise RuntimeError("Import and load a collection first.")

        prompt = build_deck_prompt(collection, commander, theme, bracket_target, extra_prompt)
        emit("Creating Cursor agent...")
        options = AgentOptions(
            api_key=api_key,
            model=model,
            local=LocalAgentOptions(cwd=str(Path.cwd())),
        )
        agent = Agent.create(options)
        emit("Sending request to Cursor...")

        last_message = ""

        def emit_unique(message: str) -> None:
            nonlocal last_message
            if message and message != last_message:
                last_message = message
                emit(message)

        def on_step(step) -> None:  # noqa: ANN001
            emit_unique(self._format_step_update(step))

        def on_delta(update) -> None:  # noqa: ANN001
            message = self._format_delta_update(update)
            if message:
                emit_unique(message)

        send_options = (
            SendOptions(on_step=on_step, on_delta=on_delta)
            if SendOptions is not None
            else None
        )
        run = agent.send(prompt, send_options)
        result = run.wait()
        if result.status != "finished":
            raise RuntimeError(f"Cursor deck build failed with status: {result.status}")
        emit("Cursor finished. Parsing deck list...")
        deck = parse_deck_csv(result.result or "")
        emit("Applying MTG Commander guardrails...")
        return enforce_ai_commander_guardrails(collection, deck, commander)

    def test_connection(self, api_key: str, model: str) -> str:
        if not HAS_CURSOR_SDK:
            raise RuntimeError("cursor-sdk is not installed. Install dependencies first.")
        if not api_key:
            raise RuntimeError("Missing CURSOR_API_KEY.")
        if not model:
            raise RuntimeError("Missing CURSOR_MODEL.")

        options = AgentOptions(
            api_key=api_key,
            model=model,
            local=LocalAgentOptions(cwd=str(Path.cwd())),
        )
        result = Agent.prompt("Reply with OK only.", options)
        if result.status != "finished":
            raise RuntimeError(f"Cursor test failed with status: {result.status}")
        return f"Connected to Cursor SDK with model '{model}'."

    def list_models(self, api_key: str) -> List[str]:
        if not HAS_CURSOR_SDK:
            raise RuntimeError("cursor-sdk is not installed. Install dependencies first.")
        if not api_key:
            raise RuntimeError("Missing CURSOR_API_KEY.")

        bridge = None
        try:
            bridge = Bridge.launch(workspace=str(Path.cwd()))
            client = Client(endpoint=bridge.endpoint)
            models = client.list_models(api_key=api_key)
        except Exception as err:
            raise RuntimeError(f"Could not fetch Cursor models: {err}") from err
        finally:
            if bridge is not None:
                try:
                    bridge.close()
                except Exception:
                    pass

        model_names: List[str] = []
        for item in models:
            model_id = self._extract_attr(item, "id")
            if isinstance(model_id, str) and model_id.strip():
                model_names.append(model_id.strip())
        if not model_names:
            raise RuntimeError("No models returned by Cursor SDK.")
        return sorted(set(model_names))

    def _format_step_update(self, step) -> str:  # noqa: ANN001
        step_type = self._extract_attr(step, "type") or "step"
        label = self._extract_attr(step, "name") or self._extract_attr(step, "title")
        if label:
            return f"Cursor: {label}"
        return f"Cursor event: {step_type}"

    def _format_delta_update(self, update) -> str:  # noqa: ANN001
        update_type = (self._extract_attr(update, "type") or "").lower()
        if "tool_call_started" in update_type:
            tool_name = self._extract_attr(update, "tool_name") or self._extract_attr(update, "name")
            return f"Cursor tool started: {tool_name or 'tool'}"
        if "tool_call_completed" in update_type:
            tool_name = self._extract_attr(update, "tool_name") or self._extract_attr(update, "name")
            return f"Cursor tool finished: {tool_name or 'tool'}"
        if "summary_started" in update_type:
            return "Cursor is summarizing progress..."
        if "summary_completed" in update_type:
            return "Cursor summary complete."
        if "turn_ended" in update_type:
            return "Cursor finished generating output."
        if "step_started" in update_type:
            step_name = self._extract_attr(update, "step_name") or self._extract_attr(update, "name")
            return f"Cursor step started: {step_name or 'step'}"
        if "step_completed" in update_type:
            step_name = self._extract_attr(update, "step_name") or self._extract_attr(update, "name")
            return f"Cursor step complete: {step_name or 'step'}"
        if "thinking_completed" in update_type:
            return "Cursor finished reasoning."
        return ""

    def _extract_attr(self, obj, key: str):  # noqa: ANN001
        if hasattr(obj, key):
            return getattr(obj, key)
        if isinstance(obj, dict):
            return obj.get(key)
        return None


class OfflineDeckClient:
    provider_label = "Offline Heuristic (No AI)"

    LAND_HINTS = (
        "forest",
        "tower",
        "passage",
        "landscape",
        "expanse",
        "wilds",
        "barrens",
        "terrace",
        "field",
        "quarter",
        "citadel",
        "palace",
        "maze",
        "thicket",
        "beacon",
        "tunnel",
        "village",
        "town",
        "grotto",
        "arena",
        "temple",
        "path",
        "haven",
        "sanctuary",
        "bridge",
        "desert",
    )

    THEME_HINTS = (
        "poison",
        "infect",
        "toxic",
        "venom",
        "blight",
        "phyrex",
        "prolifer",
        "fang",
        "deathtouch",
        "contag",
    )

    def build_deck(
        self,
        collection: CollectionStore,
        commander: str,
        theme: str,
        bracket_target: str,
        extra_prompt: str,
        api_key: str,
        model: str,
        status_callback: Callable[[str], None] | None = None,
    ) -> List[DeckCard]:
        _ = bracket_target, extra_prompt, api_key, model
        if status_callback is not None:
            status_callback("Building deck with offline heuristics...")
        if not collection.cards:
            raise RuntimeError("Import and load a collection first.")

        names = sorted(collection.cards.keys())
        lower_name_map = {n.lower(): n for n in names}
        commander_card = lower_name_map.get(commander.lower())
        if not commander_card:
            raise RuntimeError(f"Commander '{commander}' not found in collection.")

        land_pool: List[str] = []
        nonland_pool: List[str] = []
        for name in names:
            if name == commander_card:
                continue
            lowered = name.lower()
            if self._is_land_name(lowered):
                land_pool.append(name)
            else:
                nonland_pool.append(name)

        selected_nonlands = self._pick_nonlands(nonland_pool, theme, commander)
        land_cards = self._pick_lands(land_pool, collection.cards)

        deck: List[DeckCard] = [DeckCard(section="Commander", name=commander_card, quantity=1)]
        deck.extend(DeckCard(section="Nonland", name=name, quantity=1) for name in selected_nonlands)
        deck.extend(DeckCard(section="Land", name=name, quantity=qty) for name, qty in land_cards)

        if sum(card.quantity for card in deck) != 100:
            raise RuntimeError("Offline deck builder could not create a valid 100-card deck.")
        if status_callback is not None:
            status_callback("Offline deck generation complete.")
        return deck

    def test_connection(self, api_key: str, model: str) -> str:
        _ = api_key, model
        return "Offline mode is always available (no API required)."

    def _is_land_name(self, lowered_name: str) -> bool:
        if lowered_name == "forest":
            return True
        return any(hint in lowered_name for hint in self.LAND_HINTS)

    def _pick_nonlands(self, nonland_pool: List[str], theme: str, commander: str) -> List[str]:
        theme_tokens = [token for token in (theme + " " + commander).lower().replace(",", " ").split() if token]

        def score(name: str) -> Tuple[int, str]:
            lowered = name.lower()
            score_value = 0
            for hint in self.THEME_HINTS:
                if hint in lowered:
                    score_value += 8
            for token in theme_tokens:
                if token in lowered:
                    score_value += 3
            if "sol ring" in lowered or "arcane signet" in lowered:
                score_value += 10
            if "greaves" in lowered or "boots" in lowered:
                score_value += 6
            if "rampant growth" in lowered or "cultivate" in lowered:
                score_value += 5
            return (score_value, name)

        ranked = sorted(nonland_pool, key=score, reverse=True)
        if len(ranked) < 63:
            raise RuntimeError("Not enough nonland cards in collection for offline deck build.")
        return ranked[:63]

    def _pick_lands(self, land_pool: List[str], quantities: Dict[str, int]) -> List[Tuple[str, int]]:
        lands: List[Tuple[str, int]] = []
        needed = 36

        forest_qty = quantities.get("Forest", 0)
        if forest_qty > 0:
            forest_used = min(forest_qty, needed)
            lands.append(("Forest", forest_used))
            needed -= forest_used

        for name in sorted(land_pool):
            if needed <= 0:
                break
            if name == "Forest":
                continue
            lands.append((name, 1))
            needed -= 1

        if needed > 0:
            basics = ["Island", "Swamp", "Mountain", "Plains", "Wastes"]
            for basic in basics:
                qty = quantities.get(basic, 0)
                if qty <= 0 or basic == "Forest":
                    continue
                use_qty = min(qty, needed)
                lands.append((basic, use_qty))
                needed -= use_qty
                if needed == 0:
                    break

        if needed > 0:
            raise RuntimeError("Not enough lands in collection for offline deck build.")
        return lands
