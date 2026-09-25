#!/usr/bin/env python3
from commander_deck_builder import (
    Agent,
    AgentOptions,
    CursorSdkDeckClient,
    DeckBuilderApp,
    DeckBuilderWindow,
    FrontierDeckClient,
    HAS_CURSOR_SDK,
    LocalAgentOptions,
    OfflineDeckClient,
)

__all__ = [
    "Agent",
    "AgentOptions",
    "CursorSdkDeckClient",
    "DeckBuilderApp",
    "DeckBuilderWindow",
    "FrontierDeckClient",
    "HAS_CURSOR_SDK",
    "LocalAgentOptions",
    "OfflineDeckClient",
]


def main() -> None:
    DeckBuilderApp().run()


if __name__ == "__main__":
    main()
