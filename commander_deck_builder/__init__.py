from .clients import (
    Agent,
    AgentOptions,
    CursorSdkDeckClient,
    FrontierDeckClient,
    HAS_CURSOR_SDK,
    LocalAgentOptions,
    OfflineDeckClient,
)
from .models import DeckCard

__all__ = [
    "Agent",
    "AgentOptions",
    "CursorSdkDeckClient",
    "DeckBuilderApp",
    "DeckBuilderWindow",
    "DeckCard",
    "FrontierDeckClient",
    "HAS_CURSOR_SDK",
    "LocalAgentOptions",
    "OfflineDeckClient",
]


def __getattr__(name: str):
    if name in ("DeckBuilderApp", "DeckBuilderWindow"):
        from .ui import DeckBuilderApp, DeckBuilderWindow

        return DeckBuilderApp if name == "DeckBuilderApp" else DeckBuilderWindow
    raise AttributeError(f"module 'commander_deck_builder' has no attribute '{name}'")
