import io
import json
import sys
import types
import urllib.error
import unittest
from unittest.mock import patch

from commander_deck_builder.collection import CollectionStore
from commander_deck_builder.clients import OfflineDeckClient


def _install_gtk_stubs() -> None:
    if "gi" in sys.modules and "gi.repository" in sys.modules:
        return

    gi = types.ModuleType("gi")
    repository = types.ModuleType("gi.repository")

    def require_version(_name: str, _version: str) -> None:
        return None

    gi.require_version = require_version
    gi.repository = repository

    gtk = types.SimpleNamespace(
        ApplicationWindow=type("ApplicationWindow", (object,), {}),
        Application=type("Application", (object,), {}),
        Box=type("Box", (object,), {}),
        Label=type("Label", (object,), {}),
        Button=type("Button", (object,), {}),
        Entry=type("Entry", (object,), {}),
        TextView=type("TextView", (object,), {}),
        ScrolledWindow=type("ScrolledWindow", (object,), {}),
        ListBox=type("ListBox", (object,), {}),
        ListBoxRow=type("ListBoxRow", (object,), {}),
        Picture=type("Picture", (object,), {}),
        FileChooserNative=type("FileChooserNative", (object,), {}),
        DropDown=type("DropDown", (object,), {}),
        Widget=type("Widget", (object,), {}),
        StringList=type("StringList", (), {"new": staticmethod(lambda items: items)}),
        Orientation=types.SimpleNamespace(HORIZONTAL=0, VERTICAL=1),
        WrapMode=types.SimpleNamespace(WORD=0),
        FileChooserAction=types.SimpleNamespace(OPEN=0),
        ResponseType=types.SimpleNamespace(ACCEPT=1),
    )
    repository.Gtk = gtk
    repository.GLib = types.SimpleNamespace(idle_add=lambda *args, **kwargs: None)
    repository.Gdk = types.SimpleNamespace(Display=types.SimpleNamespace(get_default=lambda: None))
    repository.GdkPixbuf = types.SimpleNamespace(
        Pixbuf=types.SimpleNamespace(new_from_file_at_scale=lambda *args, **kwargs: None)
    )

    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository


_install_gtk_stubs()

import deck_builder_app  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class TestFrontierConnectivity(unittest.TestCase):
    def test_frontier_connection_success(self):
        client = deck_builder_app.FrontierDeckClient()
        payload = {
            "choices": [{"message": {"content": "OK"}}],
        }
        with patch(
            "commander_deck_builder.clients.urllib.request.urlopen",
            return_value=_FakeResponse(payload),
        ):
            message = client.test_connection(api_key="test-key", model="gpt-4.1")
        self.assertIn("Connected to OpenAI-compatible API", message)

    def test_frontier_connection_missing_key(self):
        client = deck_builder_app.FrontierDeckClient()
        with self.assertRaises(RuntimeError) as ctx:
            client.test_connection(api_key="", model="gpt-4.1")
        self.assertIn("Missing FRONTIER_API_KEY", str(ctx.exception))

    def test_frontier_connection_http_error(self):
        client = deck_builder_app.FrontierDeckClient()
        http_error = urllib.error.HTTPError(
            url="https://api.example.com/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"unauthorized"}'),
        )
        with patch("commander_deck_builder.clients.urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(RuntimeError) as ctx:
                client.test_connection(api_key="bad-key", model="gpt-4.1")
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_frontier_list_models_success(self):
        client = deck_builder_app.FrontierDeckClient()
        payload = {
            "data": [{"id": "gpt-4.1"}, {"id": "gpt-4o"}, {"id": "gpt-4.1"}],
        }
        with patch(
            "commander_deck_builder.clients.urllib.request.urlopen",
            return_value=_FakeResponse(payload),
        ):
            models = client.list_models(api_key="test-key")
        self.assertEqual(models, ["gpt-4.1", "gpt-4o"])

    def test_frontier_list_models_missing_key(self):
        client = deck_builder_app.FrontierDeckClient()
        with self.assertRaises(RuntimeError) as ctx:
            client.list_models(api_key="")
        self.assertIn("Missing FRONTIER_API_KEY", str(ctx.exception))

    def test_frontier_list_models_http_error(self):
        client = deck_builder_app.FrontierDeckClient()
        http_error = urllib.error.HTTPError(
            url="https://api.example.com/models",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"forbidden"}'),
        )
        with patch("commander_deck_builder.clients.urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(RuntimeError) as ctx:
                client.list_models(api_key="bad-key")
        self.assertIn("HTTP 403", str(ctx.exception))


class TestCursorConnectivity(unittest.TestCase):
    @patch("commander_deck_builder.clients.HAS_CURSOR_SDK", True)
    @patch("commander_deck_builder.clients.LocalAgentOptions", side_effect=lambda **kwargs: kwargs)
    @patch("commander_deck_builder.clients.AgentOptions", side_effect=lambda **kwargs: kwargs)
    @patch("commander_deck_builder.clients.Agent")
    def test_cursor_connection_success(self, mock_agent, _mock_agent_options, _mock_local_options):
        mock_agent.prompt.return_value = types.SimpleNamespace(status="finished", result="OK")
        client = deck_builder_app.CursorSdkDeckClient()
        message = client.test_connection(api_key="cursor_key", model="composer-2.5")
        self.assertIn("Connected to Cursor SDK", message)
        mock_agent.prompt.assert_called_once()

    @patch("commander_deck_builder.clients.HAS_CURSOR_SDK", False)
    def test_cursor_connection_missing_sdk(self):
        client = deck_builder_app.CursorSdkDeckClient()
        with self.assertRaises(RuntimeError) as ctx:
            client.test_connection(api_key="cursor_key", model="composer-2.5")
        self.assertIn("cursor-sdk is not installed", str(ctx.exception))

    @patch("commander_deck_builder.clients.HAS_CURSOR_SDK", True)
    def test_cursor_connection_missing_key(self):
        client = deck_builder_app.CursorSdkDeckClient()
        with self.assertRaises(RuntimeError) as ctx:
            client.test_connection(api_key="", model="composer-2.5")
        self.assertIn("Missing CURSOR_API_KEY", str(ctx.exception))

    @patch("commander_deck_builder.clients.HAS_CURSOR_SDK", True)
    @patch("commander_deck_builder.clients.LocalAgentOptions", side_effect=lambda **kwargs: kwargs)
    @patch("commander_deck_builder.clients.AgentOptions", side_effect=lambda **kwargs: kwargs)
    @patch("commander_deck_builder.clients.Agent")
    def test_cursor_connection_non_finished_status(
        self, mock_agent, _mock_agent_options, _mock_local_options
    ):
        mock_agent.prompt.return_value = types.SimpleNamespace(status="error", result="")
        client = deck_builder_app.CursorSdkDeckClient()
        with self.assertRaises(RuntimeError) as ctx:
            client.test_connection(api_key="cursor_key", model="composer-2.5")
        self.assertIn("Cursor test failed with status: error", str(ctx.exception))

    @patch("commander_deck_builder.clients.HAS_CURSOR_SDK", True)
    @patch("commander_deck_builder.clients.Client")
    @patch("commander_deck_builder.clients.Bridge")
    def test_cursor_list_models_success(self, mock_bridge_cls, mock_client_cls):
        mock_bridge = types.SimpleNamespace(endpoint=object())
        close_mock = types.SimpleNamespace(called=False)

        def _close() -> None:
            close_mock.called = True

        mock_bridge.close = _close
        mock_bridge_cls.launch.return_value = mock_bridge
        mock_client_instance = mock_client_cls.return_value
        mock_client_instance.list_models.return_value = [
            types.SimpleNamespace(id="composer-2.5"),
            types.SimpleNamespace(id="gpt-5.6-sol"),
            types.SimpleNamespace(id="composer-2.5"),
        ]

        client = deck_builder_app.CursorSdkDeckClient()
        models = client.list_models(api_key="cursor_key")
        self.assertEqual(models, ["composer-2.5", "gpt-5.6-sol"])
        self.assertTrue(close_mock.called)

    @patch("commander_deck_builder.clients.HAS_CURSOR_SDK", True)
    def test_cursor_list_models_missing_key(self):
        client = deck_builder_app.CursorSdkDeckClient()
        with self.assertRaises(RuntimeError) as ctx:
            client.list_models(api_key="")
        self.assertIn("Missing CURSOR_API_KEY", str(ctx.exception))

    @patch("commander_deck_builder.clients.HAS_CURSOR_SDK", True)
    @patch("commander_deck_builder.clients.Bridge")
    def test_cursor_list_models_error(self, mock_bridge_cls):
        mock_bridge_cls.launch.side_effect = RuntimeError("bridge unavailable")
        client = deck_builder_app.CursorSdkDeckClient()
        with self.assertRaises(RuntimeError) as ctx:
            client.list_models(api_key="cursor_key")
        self.assertIn("Could not fetch Cursor models", str(ctx.exception))


class TestOfflineConnectivityAndBuild(unittest.TestCase):
    def test_offline_connection_always_available(self):
        client = OfflineDeckClient()
        message = client.test_connection(api_key="", model="")
        self.assertIn("always available", message)

    def test_offline_build_produces_100_cards(self):
        collection = CollectionStore()
        cards = {"Fynn, the Fangbearer": 1, "Forest": 36}
        for idx in range(1, 70):
            cards[f"Spell {idx}"] = 1
        collection.cards = cards
        collection.card_meta = {}

        client = OfflineDeckClient()
        deck = client.build_deck(
            collection=collection,
            commander="Fynn, the Fangbearer",
            theme="poison",
            bracket_target="3",
            extra_prompt="",
            api_key="",
            model="",
        )
        self.assertEqual(sum(card.quantity for card in deck), 100)
        self.assertEqual(deck[0].section, "Commander")
        self.assertEqual(deck[0].name, "Fynn, the Fangbearer")


if __name__ == "__main__":
    unittest.main()
