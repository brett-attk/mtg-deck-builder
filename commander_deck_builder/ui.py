import csv
import os
import queue
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from .clients import CursorSdkDeckClient, FrontierDeckClient, OfflineDeckClient
from .collection import CollectionStore
from .config import AppConfig
from .deck_naming import choose_generated_deck_path
from .exporters import format_quantity_name_set_lines
from .models import DeckCard
from .scryfall import ScryfallImageCache

CARD_TYPE_ORDER = ["Creature", "Artifact", "Enchantment", "Instant", "Sorcery", "Land", "Other"]
TOP_CURSOR_MODELS = [
    "composer-2.5",
    "gpt-5.6-sol-medium",
    "claude-opus-5-thinking-high",
    "claude-fable-5-1-thinking-high",
    "cursor-grok-4.6-high-fast",
    "muse-spark-1.3-high",
]
TOP_OPENAI_COMPAT_MODELS = [
    "gpt-4.1",
    "gpt-4o",
    "gpt-4.1-mini",
    "o4-mini",
]


class DeckBuilderWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title="Commander Deck Builder")
        self.set_default_size(1200, 740)

        self.workspace_dir = Path.cwd()
        self.collections_dir = self.workspace_dir / "collections"
        self.generated_decks_dir = self.workspace_dir / "generated-decks"
        self.collections_dir.mkdir(parents=True, exist_ok=True)
        self.generated_decks_dir.mkdir(parents=True, exist_ok=True)

        self.collection = CollectionStore()
        self.config = AppConfig()
        self.clients: Dict[str, object] = {
            "offline": OfflineDeckClient(),
            "cursor": CursorSdkDeckClient(),
            "openai": FrontierDeckClient(),
        }
        self.settings_dialog: Optional[Gtk.Window] = None
        self.collection_dialog: Optional[Gtk.Window] = None
        self.collection_dialog_label: Optional[Gtk.Label] = None
        self.builder_dialog: Optional[Gtk.Window] = None
        self.builder_deck_name_entry: Optional[Gtk.Entry] = None
        self.builder_commander_entry: Optional[Gtk.Entry] = None
        self.builder_theme_entry: Optional[Gtk.Entry] = None
        self.builder_bracket_entry: Optional[Gtk.Entry] = None
        self.builder_prompt_view: Optional[Gtk.TextView] = None
        self.builder_build_button: Optional[Gtk.Button] = None
        self.builder_progress_box: Optional[Gtk.Box] = None
        self.builder_progress_label: Optional[Gtk.Label] = None
        self.builder_progress_spinner: Optional[Gtk.Spinner] = None
        self.pending_deck_name: str = ""
        self.settings_provider_dropdown: Optional[Gtk.DropDown] = None
        self.settings_cursor_key_entry: Optional[Gtk.Entry] = None
        self.settings_cursor_model_entry: Optional[Gtk.Entry] = None
        self.settings_cursor_model_dropdown: Optional[Gtk.DropDown] = None
        self.settings_cursor_model_options: List[str] = []
        self.fetched_cursor_models: List[str] = []
        self.settings_frontier_key_entry: Optional[Gtk.Entry] = None
        self.settings_frontier_model_entry: Optional[Gtk.Entry] = None
        self.settings_frontier_model_dropdown: Optional[Gtk.DropDown] = None
        self.settings_frontier_model_options: List[str] = []
        self.fetched_frontier_models: List[str] = []
        self.settings_test_cursor_button: Optional[Gtk.Button] = None
        self.settings_fetch_cursor_models_button: Optional[Gtk.Button] = None
        self.settings_test_frontier_button: Optional[Gtk.Button] = None
        self.settings_fetch_frontier_models_button: Optional[Gtk.Button] = None
        self.settings_save_button: Optional[Gtk.Button] = None
        self.deck_cards: List[DeckCard] = []
        self.collection_display_rows: List[Tuple[str, int, Dict[str, str]]] = []
        self.collection_rows: List[Optional[Tuple[str, int, Dict[str, str]]]] = []
        self.collection_view_mode_dropdown: Optional[Gtk.DropDown] = None
        self.collection_type_filter_dropdown: Optional[Gtk.DropDown] = None
        self.collection_type_filter_box: Optional[Gtk.Widget] = None
        self.collection_type_filter_options: List[str] = []
        self.collection_type_filter_updating = False
        self.collection_type_filter_refresh_token = 0
        self.collection_type_filter_force_all_once = True
        self.collection_loading_box: Optional[Gtk.Box] = None
        self.collection_loading_label: Optional[Gtk.Label] = None
        self.collection_loading_spinner: Optional[Gtk.Spinner] = None
        self.collection_stack: Optional[Gtk.Stack] = None
        self.collection_list_scroll: Optional[Gtk.ScrolledWindow] = None
        self.collection_grid_scroll: Optional[Gtk.ScrolledWindow] = None
        self.collection_grid: Optional[Gtk.FlowBox] = None
        self.collection_render_token = 0
        self.collection_list_render_token = 0
        self.collection_list_render_entries: List[Dict[str, object]] = []
        self.collection_list_render_index = 0
        self.collection_list_chunk_size = 180
        self.collection_grid_render_token = 0
        self.collection_grid_rows: List[Tuple[str, int, Dict[str, str]]] = []
        self.collection_grid_next_index = 0
        self.collection_grid_batch_size = 72
        self.collection_grid_chunk_size = 18
        self.collection_grid_target_index = 0
        self.collection_grid_append_in_progress = False
        self.collection_group_render_token = 0
        self.collection_grid_visible_start_index = 0
        self.collection_grid_visible_end_index = 0
        self.collection_prefetch_priority_cards: List[Tuple[str, Dict[str, str]]] = []
        self.collection_prefetch_priority_lock = threading.Lock()
        self.collection_thumbnail_queue: Optional[queue.Queue] = None
        self.collection_thumbnail_worker: Optional[threading.Thread] = None
        self.collection_thumbnail_worker_token: int = 0
        self.collection_grid_complete_sent = False
        self.saved_deck_cards: List[DeckCard] = []
        self.saved_deck_rows: List[Optional[DeckCard]] = []
        self.saved_deck_files: List[Path] = []
        self.scryfall_status_value = "Scryfall: idle."
        self.scryfall_activity_message = "idle."
        self.scryfall_coverage_suffix = ""
        self.scryfall_status_label: Optional[Gtk.Label] = None
        self.image_cache = ScryfallImageCache(activity_callback=self._on_scryfall_activity)
        self.collection_prefetch_stop_event = threading.Event()
        self.collection_prefetch_wake_event = threading.Event()
        self.collection_prefetch_thread = threading.Thread(
            target=self._collection_image_prefetch_worker,
            daemon=True,
        )
        self.connect("close-request", self._on_close_request)

        self._install_css()
        self._build_ui()
        self._try_autoload_collection()
        self._refresh_saved_decks()
        self.collection_prefetch_thread.start()

    def _install_css(self) -> None:
        css = b"""
        .thumb-skeleton {
            min-width: 140px;
            min-height: 195px;
            border-radius: 8px;
            background-color: alpha(@theme_fg_color, 0.10);
            animation: thumbPulse 900ms ease-in-out infinite alternate;
        }
        .thumb-missing {
            min-width: 140px;
            min-height: 195px;
            border-radius: 8px;
            background-color: alpha(@theme_fg_color, 0.06);
        }
        @keyframes thumbPulse {
            from { background-color: alpha(@theme_fg_color, 0.07); }
            to { background-color: alpha(@theme_fg_color, 0.18); }
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _build_ui(self) -> None:
        root_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root_outer.set_margin_start(12)
        root_outer.set_margin_end(12)
        root_outer.set_margin_top(12)
        root_outer.set_margin_bottom(12)
        self.set_child(root_outer)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_label = Gtk.Label(xalign=0)
        header_label.set_hexpand(True)
        header_label.set_text("Commander Deck Builder")
        header.append(header_label)
        settings_button = Gtk.Button(label="Settings")
        settings_button.connect("clicked", self._on_open_settings_clicked)
        header.append(settings_button)
        collection_button = Gtk.Button(label="Collection Manager")
        collection_button.connect("clicked", self._on_open_collection_clicked)
        header.append(collection_button)
        deck_builder_button = Gtk.Button(label="Deck Builder")
        deck_builder_button.connect("clicked", self._on_open_builder_clicked)
        header.append(deck_builder_button)
        root_outer.append(header)

        self.collection_label = Gtk.Label(xalign=0)
        self.collection_label.set_text("Collection: not loaded")
        root_outer.append(self.collection_label)

        self.status_label = Gtk.Label(xalign=0)
        self.status_label.set_wrap(True)
        self.status_label.set_text("Ready.")
        root_outer.append(self.status_label)

        content_area = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        content_area.set_wide_handle(True)
        content_area.set_hexpand(True)
        content_area.set_vexpand(True)
        # Keep a stable split so card/image content does not resize panes.
        content_area.set_position(760)
        root_outer.append(content_area)

        list_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        list_pane.set_hexpand(True)
        list_pane.set_vexpand(True)
        content_area.set_start_child(list_pane)
        content_area.set_resize_start_child(True)
        content_area.set_shrink_start_child(True)

        preview_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview_pane.set_size_request(380, -1)
        preview_pane.set_hexpand(False)
        preview_pane.set_vexpand(True)
        content_area.set_end_child(preview_pane)
        content_area.set_resize_end_child(False)
        content_area.set_shrink_end_child(False)

        self.content_tabs = Gtk.Notebook()
        self.content_tabs.set_hexpand(True)
        self.content_tabs.set_vexpand(True)
        list_pane.append(self.content_tabs)

        collection_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        collection_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.collection_view_mode_model = Gtk.StringList.new(["List", "Grid Thumbnails"])
        self.collection_view_mode_dropdown = Gtk.DropDown.new(self.collection_view_mode_model, None)
        self.collection_view_mode_dropdown.set_selected(0)
        self.collection_view_mode_dropdown.connect("notify::selected", self._on_collection_view_mode_changed)
        collection_controls.append(self._labeled("View Mode", self.collection_view_mode_dropdown))
        self.collection_group_model = Gtk.StringList.new(["Name", "Card Type"])
        self.collection_group_dropdown = Gtk.DropDown.new(self.collection_group_model, None)
        self.collection_group_dropdown.set_selected(0)
        self.collection_group_dropdown.connect("notify::selected", self._on_collection_group_mode_changed)
        collection_controls.append(self._labeled("View Grouping", self.collection_group_dropdown))
        self.collection_type_filter_dropdown = Gtk.DropDown.new(Gtk.StringList.new([]), None)
        self.collection_type_filter_dropdown.connect(
            "notify::selected", self._on_collection_type_filter_selected
        )
        self.collection_type_filter_box = self._labeled("Type Filter", self.collection_type_filter_dropdown)
        self.collection_type_filter_box.set_visible(False)
        collection_controls.append(self.collection_type_filter_box)
        collection_container.append(collection_controls)

        self.collection_loading_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.collection_loading_spinner = Gtk.Spinner()
        self.collection_loading_spinner.set_size_request(18, 18)
        self.collection_loading_label = Gtk.Label(xalign=0)
        self.collection_loading_label.set_hexpand(True)
        self.collection_loading_label.set_wrap(True)
        self.collection_loading_box.append(self.collection_loading_spinner)
        self.collection_loading_box.append(self.collection_loading_label)
        self.collection_loading_box.set_visible(False)
        collection_container.append(self.collection_loading_box)

        self.collection_stack = Gtk.Stack()
        self.collection_stack.set_vexpand(True)

        self.collection_list = Gtk.ListBox()
        self.collection_list.connect("row-selected", self._on_collection_selected)
        self.collection_list_scroll = Gtk.ScrolledWindow()
        self.collection_list_scroll.set_vexpand(True)
        self.collection_list_scroll.set_child(self.collection_list)
        self.collection_stack.add_named(self.collection_list_scroll, "list")

        self.collection_grid = Gtk.FlowBox()
        self.collection_grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.collection_grid.set_max_children_per_line(3)
        self.collection_grid.set_min_children_per_line(3)
        self.collection_grid.set_row_spacing(10)
        self.collection_grid.set_column_spacing(10)
        self.collection_grid_scroll = Gtk.ScrolledWindow()
        self.collection_grid_scroll.set_vexpand(True)
        self.collection_grid_scroll.set_child(self.collection_grid)
        grid_adjustment = self.collection_grid_scroll.get_vadjustment()
        if grid_adjustment is not None:
            grid_adjustment.connect("value-changed", self._on_collection_grid_scroll_changed)
        self.collection_stack.add_named(self.collection_grid_scroll, "grid")
        self.collection_stack.set_visible_child_name("list")
        collection_container.append(self.collection_stack)
        self.content_tabs.append_page(collection_container, Gtk.Label(label="Collection"))

        saved_decks_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.saved_decks_model = Gtk.StringList.new([])
        self.saved_decks_dropdown = Gtk.DropDown.new(self.saved_decks_model, None)
        self.saved_decks_dropdown.connect("notify::selected", self._on_saved_deck_changed)
        saved_decks_container.append(self._labeled("Generated Deck File", self.saved_decks_dropdown))
        self.saved_decks_group_model = Gtk.StringList.new(["Deck Order", "Card Type"])
        self.saved_decks_group_dropdown = Gtk.DropDown.new(self.saved_decks_group_model, None)
        self.saved_decks_group_dropdown.set_selected(0)
        self.saved_decks_group_dropdown.connect("notify::selected", self._on_saved_deck_group_mode_changed)
        saved_decks_container.append(self._labeled("View Grouping", self.saved_decks_group_dropdown))
        generated_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refresh_saved_button = Gtk.Button(label="Refresh Generated Decks")
        refresh_saved_button.connect("clicked", self._on_refresh_saved_decks_clicked)
        generated_actions.append(refresh_saved_button)
        copy_generated_button = Gtk.Button(label="Copy Generated Deck")
        copy_generated_button.connect("clicked", self._on_copy_generated_deck_clicked)
        generated_actions.append(copy_generated_button)
        delete_generated_button = Gtk.Button(label="Delete Deck")
        delete_generated_button.connect("clicked", self._on_delete_generated_deck_clicked)
        generated_actions.append(delete_generated_button)
        saved_decks_container.append(generated_actions)
        self.saved_decks_list = Gtk.ListBox()
        self.saved_decks_list.connect("row-selected", self._on_saved_deck_card_selected)
        saved_decks_scroll = Gtk.ScrolledWindow()
        saved_decks_scroll.set_vexpand(True)
        saved_decks_scroll.set_child(self.saved_decks_list)
        saved_decks_container.append(saved_decks_scroll)
        self.content_tabs.append_page(saved_decks_container, Gtk.Label(label="Generated Decks"))

        self.card_title = Gtk.Label(xalign=0)
        self.card_title.set_wrap(True)
        self.card_title.set_max_width_chars(40)
        self.card_title.set_text("Select a card to preview.")
        preview_pane.append(self.card_title)

        self.card_details = Gtk.Label(xalign=0)
        self.card_details.set_wrap(True)
        self.card_details.set_max_width_chars(44)
        self.card_details.set_text("Card details will appear here.")
        preview_pane.append(self.card_details)

        self.preview_stack = Gtk.Stack()
        self.preview_stack.set_vexpand(True)
        self.preview_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        loading_box.set_vexpand(True)
        loading_box.set_hexpand(True)
        loading_box.set_halign(Gtk.Align.CENTER)
        loading_box.set_valign(Gtk.Align.CENTER)
        self.loading_spinner = Gtk.Spinner()
        self.loading_spinner.set_size_request(48, 48)
        loading_label = Gtk.Label(label="Loading card image...")
        loading_box.append(self.loading_spinner)
        loading_box.append(loading_label)

        self.card_picture = Gtk.Picture()
        self.card_picture.set_can_shrink(True)
        self.card_picture.set_size_request(360, 500)
        image_scroll = Gtk.ScrolledWindow()
        image_scroll.set_vexpand(True)
        image_scroll.set_child(self.card_picture)

        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty_box.set_vexpand(True)
        empty_box.set_hexpand(True)
        empty_box.set_halign(Gtk.Align.CENTER)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.append(Gtk.Label(label="No image loaded"))

        self.preview_stack.add_named(loading_box, "loading")
        self.preview_stack.add_named(image_scroll, "image")
        self.preview_stack.add_named(empty_box, "empty")
        self.preview_stack.set_visible_child_name("empty")
        preview_pane.append(self.preview_stack)

        scryfall_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        scryfall_bar.set_size_request(-1, 24)
        scryfall_bar.set_margin_top(4)
        scryfall_label = Gtk.Label(xalign=0)
        scryfall_label.set_hexpand(True)
        scryfall_label.set_wrap(False)
        scryfall_label.set_text(self.scryfall_status_value)
        scryfall_bar.append(scryfall_label)
        self.scryfall_status_label = scryfall_label
        root_outer.append(scryfall_bar)

    def _labeled(self, title: str, child: Gtk.Widget) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label = Gtk.Label(xalign=0)
        label.set_text(title)
        box.append(label)
        box.append(child)
        return box

    def _set_status(self, text: str) -> None:
        self.status_label.set_text(text)

    def _set_collection_loading(self, visible: bool, message: str = "") -> None:
        if self.collection_loading_box is not None:
            self.collection_loading_box.set_visible(visible)
        if self.collection_loading_label is not None:
            self.collection_loading_label.set_text(message)
        if self.collection_loading_spinner is not None:
            if visible:
                self.collection_loading_spinner.start()
            else:
                self.collection_loading_spinner.stop()

    def _on_scryfall_activity(self, message: str) -> None:
        GLib.idle_add(self._set_scryfall_status, message)

    def _set_scryfall_status(self, message: str) -> bool:
        self.scryfall_activity_message = message
        display_message = f"Scryfall: {message}{self.scryfall_coverage_suffix}"
        self.scryfall_status_value = display_message
        if self.scryfall_status_label is not None:
            self.scryfall_status_label.set_text(display_message)
        return False

    def _refresh_scryfall_status_display(self) -> None:
        self._set_scryfall_status(self.scryfall_activity_message)

    def _update_scryfall_coverage_suffix(self, cached: int, total: int) -> bool:
        if total <= 0:
            self.scryfall_coverage_suffix = ""
        else:
            pct = int(round((cached * 100) / total))
            self.scryfall_coverage_suffix = f" | Images: {cached}/{total} ({pct}%)"
        self._refresh_scryfall_status_display()
        return False

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        self.collection_prefetch_stop_event.set()
        self.collection_prefetch_wake_event.set()
        return False

    def _signal_collection_prefetch(self) -> None:
        self.collection_prefetch_wake_event.set()

    def _collection_image_prefetch_worker(self) -> None:
        while not self.collection_prefetch_stop_event.is_set():
            try:
                if self.collection.path is None or not self.collection.cards:
                    GLib.idle_add(self._update_scryfall_coverage_suffix, 0, 0)
                    if self.collection_prefetch_wake_event.wait(timeout=20):
                        self.collection_prefetch_wake_event.clear()
                    continue

                cards_to_check = self._get_prefetch_priority_cards_snapshot()
                fetched, remaining = self.image_cache.prefetch_missing_collection_images(
                    cards=cards_to_check,
                    max_to_fetch=8,
                )
                type_fetched, type_remaining = self.image_cache.prefetch_missing_type_lines(
                    card_names=[name for name, _meta in cards_to_check],
                    max_to_fetch=12,
                )
                if fetched > 0:
                    status = f"Background image sync downloaded {fetched} card image"
                    if fetched != 1:
                        status += "s"
                    if remaining > 0:
                        status += f" ({remaining} remaining)"
                    status += "."
                    GLib.idle_add(self._set_status, status)
                if type_fetched > 0:
                    GLib.idle_add(self._refresh_collection_type_grouping_if_active)
                full_collection_cards = [
                    (name, dict(meta))
                    for name, _qty, meta in self.collection.as_display_rows()
                ]
                cached_images, total_images = self.image_cache.collection_image_cache_coverage(
                    full_collection_cards
                )
                GLib.idle_add(self._update_scryfall_coverage_suffix, cached_images, total_images)
            except Exception as err:
                GLib.idle_add(self._set_status, f"Background Scryfall sync recovered from error: {err}")
                remaining = 0
                type_remaining = 0

            has_pending_work = remaining > 0 or type_remaining > 0
            wait_seconds = 75 if has_pending_work else 240
            if self.collection_prefetch_wake_event.wait(timeout=wait_seconds):
                self.collection_prefetch_wake_event.clear()

    def _set_controls_enabled(self, enabled: bool) -> None:
        if self.builder_build_button is not None:
            self.builder_build_button.set_sensitive(enabled)
        if self.settings_save_button is not None:
            self.settings_save_button.set_sensitive(enabled)
        if self.settings_test_cursor_button is not None:
            self.settings_test_cursor_button.set_sensitive(enabled)
        if self.settings_fetch_cursor_models_button is not None:
            self.settings_fetch_cursor_models_button.set_sensitive(enabled)
        if self.settings_test_frontier_button is not None:
            self.settings_test_frontier_button.set_sensitive(enabled)
        if self.settings_fetch_frontier_models_button is not None:
            self.settings_fetch_frontier_models_button.set_sensitive(enabled)

    def _resolved_cursor_key(self, mask_if_env: bool = True) -> str:
        env_key = os.getenv("CURSOR_API_KEY", "").strip()
        if env_key:
            return "******** (using CURSOR_API_KEY)" if mask_if_env else env_key
        return self.config.get("cursor_api_key", "")

    def _resolved_cursor_model(self) -> str:
        return os.getenv("CURSOR_MODEL", "").strip() or self.config.get(
            "cursor_model", "composer-2.5"
        )

    def _resolved_frontier_key(self, mask_if_env: bool = True) -> str:
        env_key = (
            os.getenv("FRONTIER_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
        )
        if env_key:
            return "******** (using environment key)" if mask_if_env else env_key
        return self.config.get("frontier_api_key", "")

    def _resolved_frontier_model(self) -> str:
        return os.getenv("FRONTIER_MODEL", "").strip() or self.config.get("frontier_model", "gpt-4.1")

    def _effective_cursor_key(self) -> str:
        if self.settings_cursor_key_entry is not None:
            value = self.settings_cursor_key_entry.get_text().strip()
            if value:
                return os.getenv("CURSOR_API_KEY", "").strip() or value
        return os.getenv("CURSOR_API_KEY", "").strip() or self.config.get("cursor_api_key", "")

    def _effective_frontier_key(self) -> str:
        env_value = os.getenv("FRONTIER_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
        if env_value:
            return env_value
        if self.settings_frontier_key_entry is not None:
            value = self.settings_frontier_key_entry.get_text().strip()
            if value:
                return value
        return self.config.get("frontier_api_key", "")

    def _effective_cursor_model(self) -> str:
        if self.settings_cursor_model_entry is not None:
            value = self.settings_cursor_model_entry.get_text().strip()
            if value:
                return value
        return self._resolved_cursor_model()

    def _effective_frontier_model(self) -> str:
        if self.settings_frontier_model_entry is not None:
            value = self.settings_frontier_model_entry.get_text().strip()
            if value:
                return value
        return self._resolved_frontier_model()

    def _selected_provider_key(self) -> str:
        if self.settings_provider_dropdown is not None:
            selected = self.settings_provider_dropdown.get_selected()
            if selected == 0:
                return "offline"
            if selected == 1:
                return "cursor"
            return "openai"
        stored = self.config.get("provider_key", "offline").strip().lower()
        if stored == "cursor":
            return "cursor"
        if stored == "openai":
            return "openai"
        return "offline"

    def _selected_provider_config(self, provider_key: str) -> tuple[str, str]:
        if provider_key == "offline":
            return ("", "")
        if provider_key == "cursor":
            return (self._effective_cursor_key(), self._effective_cursor_model() or "composer-2.5")
        return (
            self._effective_frontier_key(),
            self._effective_frontier_model() or "gpt-4.1",
        )

    def _on_open_settings_clicked(self, _button: Gtk.Button) -> None:
        self._ensure_settings_dialog()
        self.settings_dialog.present()

    def _on_open_collection_clicked(self, _button: Gtk.Button) -> None:
        self._ensure_collection_dialog()
        self.collection_dialog.present()

    def _ensure_collection_dialog(self) -> None:
        if self.collection_dialog is not None:
            return

        dialog = Gtk.Window(title="Collection Manager", transient_for=self, modal=True)
        dialog.set_default_size(500, 220)
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_margin_start(12)
        container.set_margin_end(12)
        container.set_margin_top(12)
        container.set_margin_bottom(12)
        dialog.set_child(container)

        self.collection_dialog_label = Gtk.Label(xalign=0)
        self.collection_dialog_label.set_wrap(True)
        container.append(self.collection_dialog_label)

        load_button = Gtk.Button(label="Load Collection CSV")
        load_button.connect("clicked", self._on_load_collection_clicked)
        container.append(load_button)

        close_button = Gtk.Button(label="Close")
        close_button.connect("clicked", lambda _btn: dialog.hide())
        container.append(close_button)

        self.collection_dialog = dialog
        self._update_collection_labels()

    def _on_open_builder_clicked(self, _button: Gtk.Button) -> None:
        self._ensure_builder_dialog()
        self.builder_dialog.present()

    def _ensure_builder_dialog(self) -> None:
        if self.builder_dialog is not None:
            return

        dialog = Gtk.Window(title="Deck Builder", transient_for=self, modal=True)
        dialog.set_default_size(520, 500)
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_margin_start(12)
        container.set_margin_end(12)
        container.set_margin_top(12)
        container.set_margin_bottom(12)
        dialog.set_child(container)

        self.builder_deck_name_entry = Gtk.Entry()
        self.builder_deck_name_entry.set_placeholder_text("Deck file name")
        self.builder_deck_name_entry.set_text("generated_deck")
        container.append(self._labeled("Deck Name", self.builder_deck_name_entry))

        self.builder_commander_entry = Gtk.Entry()
        self.builder_commander_entry.set_placeholder_text("Commander name")
        self.builder_commander_entry.set_text("Fynn, the Fangbearer")
        container.append(self._labeled("Commander", self.builder_commander_entry))

        self.builder_theme_entry = Gtk.Entry()
        self.builder_theme_entry.set_placeholder_text("Theme")
        self.builder_theme_entry.set_text("Poison counters")
        container.append(self._labeled("Theme", self.builder_theme_entry))

        self.builder_bracket_entry = Gtk.Entry()
        self.builder_bracket_entry.set_placeholder_text("3")
        self.builder_bracket_entry.set_text("3")
        container.append(self._labeled("Target Bracket", self.builder_bracket_entry))

        self.builder_prompt_view = Gtk.TextView()
        self.builder_prompt_view.set_wrap_mode(Gtk.WrapMode.WORD)
        prompt_scroll = Gtk.ScrolledWindow()
        prompt_scroll.set_min_content_height(120)
        prompt_scroll.set_child(self.builder_prompt_view)
        container.append(self._labeled("Extra Prompt Preferences", prompt_scroll))

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        close_button = Gtk.Button(label="Close")
        close_button.connect("clicked", lambda _btn: dialog.hide())
        self.builder_build_button = Gtk.Button(label="Build Deck")
        self.builder_build_button.connect("clicked", self._on_build_clicked)
        actions.append(close_button)
        actions.append(self.builder_build_button)
        container.append(actions)

        self.builder_progress_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.builder_progress_spinner = Gtk.Spinner()
        self.builder_progress_spinner.set_size_request(22, 22)
        self.builder_progress_label = Gtk.Label(xalign=0)
        self.builder_progress_label.set_hexpand(True)
        self.builder_progress_label.set_wrap(True)
        self.builder_progress_box.append(self.builder_progress_spinner)
        self.builder_progress_box.append(self.builder_progress_label)
        self.builder_progress_box.set_visible(False)
        container.append(self.builder_progress_box)

        self.builder_dialog = dialog

    def _ensure_settings_dialog(self) -> None:
        if self.settings_dialog is not None:
            return

        dialog = Gtk.Window(title="App Settings", transient_for=self, modal=True)
        dialog.set_default_size(520, 560)
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_margin_start(12)
        container.set_margin_end(12)
        container.set_margin_top(12)
        container.set_margin_bottom(12)
        dialog.set_child(container)

        provider_model = Gtk.StringList.new(
            [
                self.clients["offline"].provider_label,
                self.clients["cursor"].provider_label,
                self.clients["openai"].provider_label,
            ]
        )
        self.settings_provider_dropdown = Gtk.DropDown.new(provider_model, None)
        container.append(self._labeled("LLM Provider", self.settings_provider_dropdown))

        self.settings_cursor_key_entry = Gtk.Entry()
        self.settings_cursor_key_entry.set_visibility(False)
        self.settings_cursor_key_entry.set_placeholder_text("cursor_...")
        self.settings_cursor_key_entry.set_text(self.config.get("cursor_api_key", ""))
        container.append(self._labeled("Cursor API Key", self.settings_cursor_key_entry))

        self.settings_cursor_model_entry = Gtk.Entry()
        self.settings_cursor_model_entry.set_text(self._resolved_cursor_model())
        container.append(self._labeled("Cursor Model", self.settings_cursor_model_entry))
        self.settings_cursor_model_dropdown = Gtk.DropDown.new(Gtk.StringList.new([]), None)
        self.settings_cursor_model_dropdown.connect("notify::selected", self._on_cursor_model_selected)
        container.append(self._labeled("Top Cursor Models", self.settings_cursor_model_dropdown))

        self.settings_test_cursor_button = Gtk.Button(label="Test Cursor Connection")
        self.settings_test_cursor_button.connect("clicked", self._on_test_cursor_clicked)
        container.append(self.settings_test_cursor_button)
        self.settings_fetch_cursor_models_button = Gtk.Button(label="Fetch Cursor Models")
        self.settings_fetch_cursor_models_button.connect("clicked", self._on_fetch_cursor_models_clicked)
        container.append(self.settings_fetch_cursor_models_button)

        self.settings_frontier_key_entry = Gtk.Entry()
        self.settings_frontier_key_entry.set_visibility(False)
        self.settings_frontier_key_entry.set_placeholder_text("OpenAI/Frontier key")
        self.settings_frontier_key_entry.set_text(self.config.get("frontier_api_key", ""))
        container.append(self._labeled("OpenAI-Compatible API Key", self.settings_frontier_key_entry))

        self.settings_frontier_model_entry = Gtk.Entry()
        self.settings_frontier_model_entry.set_text(self._resolved_frontier_model())
        container.append(self._labeled("OpenAI-Compatible Model", self.settings_frontier_model_entry))
        self.settings_frontier_model_dropdown = Gtk.DropDown.new(Gtk.StringList.new([]), None)
        self.settings_frontier_model_dropdown.connect(
            "notify::selected", self._on_frontier_model_selected
        )
        container.append(self._labeled("Top OpenAI-Compatible Models", self.settings_frontier_model_dropdown))

        self.settings_test_frontier_button = Gtk.Button(label="Test OpenAI-Compatible Connection")
        self.settings_test_frontier_button.connect("clicked", self._on_test_frontier_clicked)
        container.append(self.settings_test_frontier_button)
        self.settings_fetch_frontier_models_button = Gtk.Button(label="Fetch Available Models")
        self.settings_fetch_frontier_models_button.connect(
            "clicked", self._on_fetch_frontier_models_clicked
        )
        container.append(self.settings_fetch_frontier_models_button)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_row.set_halign(Gtk.Align.END)
        close_button = Gtk.Button(label="Close")
        close_button.connect("clicked", lambda _btn: dialog.hide())
        self.settings_save_button = Gtk.Button(label="Save Settings")
        self.settings_save_button.connect("clicked", self._on_save_settings_clicked)
        button_row.append(close_button)
        button_row.append(self.settings_save_button)
        container.append(button_row)

        self.settings_dialog = dialog
        self._sync_settings_from_config()

    def _sync_settings_from_config(self) -> None:
        if self.settings_provider_dropdown is not None:
            selected = 0
            provider_key = self.config.get("provider_key", "offline").strip().lower()
            if provider_key == "cursor":
                selected = 1
            elif provider_key == "openai":
                selected = 2
            self.settings_provider_dropdown.set_selected(selected)
        if self.settings_cursor_key_entry is not None:
            self.settings_cursor_key_entry.set_text(self.config.get("cursor_api_key", ""))
        if self.settings_cursor_model_entry is not None:
            self.settings_cursor_model_entry.set_text(self._resolved_cursor_model())
        if self.settings_frontier_key_entry is not None:
            self.settings_frontier_key_entry.set_text(self.config.get("frontier_api_key", ""))
        if self.settings_frontier_model_entry is not None:
            self.settings_frontier_model_entry.set_text(self._resolved_frontier_model())
        self._refresh_top_model_dropdowns()

    def _build_model_option_list(self, current_model: str, suggested_models: List[str]) -> List[str]:
        options: List[str] = []
        current = current_model.strip()
        if current:
            options.append(current)
        for model_name in suggested_models:
            if model_name not in options:
                options.append(model_name)
        return options

    def _refresh_top_model_dropdowns(self) -> None:
        if self.settings_cursor_model_dropdown is not None:
            current_cursor_model = self._effective_cursor_model() or "composer-2.5"
            self.settings_cursor_model_options = self._build_model_option_list(
                current_cursor_model, TOP_CURSOR_MODELS + self.fetched_cursor_models
            )
            self.settings_cursor_model_dropdown.set_model(
                Gtk.StringList.new(self.settings_cursor_model_options)
            )
            self.settings_cursor_model_dropdown.set_selected(0)

        if self.settings_frontier_model_dropdown is not None:
            current_frontier_model = self._effective_frontier_model() or "gpt-4.1"
            self.settings_frontier_model_options = self._build_model_option_list(
                current_frontier_model, TOP_OPENAI_COMPAT_MODELS + self.fetched_frontier_models
            )
            self.settings_frontier_model_dropdown.set_model(
                Gtk.StringList.new(self.settings_frontier_model_options)
            )
            self.settings_frontier_model_dropdown.set_selected(0)

    def _on_cursor_model_selected(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        selected = dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            return
        if selected < 0 or selected >= len(self.settings_cursor_model_options):
            return
        if self.settings_cursor_model_entry is not None:
            self.settings_cursor_model_entry.set_text(self.settings_cursor_model_options[selected])

    def _on_frontier_model_selected(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        selected = dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            return
        if selected < 0 or selected >= len(self.settings_frontier_model_options):
            return
        if self.settings_frontier_model_entry is not None:
            self.settings_frontier_model_entry.set_text(self.settings_frontier_model_options[selected])

    def _on_fetch_cursor_models_clicked(self, _button: Gtk.Button) -> None:
        self._set_controls_enabled(False)
        self._set_status("Fetching available Cursor models...")
        thread = threading.Thread(target=self._fetch_cursor_models_worker, daemon=True)
        thread.start()

    def _fetch_cursor_models_worker(self) -> None:
        try:
            api_key = self._effective_cursor_key()
            models = self.clients["cursor"].list_models(api_key=api_key)
            GLib.idle_add(self._on_cursor_models_fetched, models)
        except Exception as err:
            GLib.idle_add(self._on_cursor_models_fetch_failed, str(err))

    def _on_cursor_models_fetched(self, models: List[str]) -> bool:
        self.fetched_cursor_models = models
        self._refresh_top_model_dropdowns()
        self._set_controls_enabled(True)
        self._set_status(f"Fetched {len(models)} models from Cursor SDK.")
        return False

    def _on_cursor_models_fetch_failed(self, error: str) -> bool:
        self._set_controls_enabled(True)
        self._set_status(f"Cursor model fetch failed: {error}")
        return False

    def _on_fetch_frontier_models_clicked(self, _button: Gtk.Button) -> None:
        self._set_controls_enabled(False)
        self._set_status("Fetching available OpenAI-compatible models...")
        thread = threading.Thread(target=self._fetch_frontier_models_worker, daemon=True)
        thread.start()

    def _fetch_frontier_models_worker(self) -> None:
        try:
            api_key = self._effective_frontier_key()
            models = self.clients["openai"].list_models(api_key=api_key)
            GLib.idle_add(self._on_frontier_models_fetched, models)
        except Exception as err:
            GLib.idle_add(self._on_frontier_models_fetch_failed, str(err))

    def _on_frontier_models_fetched(self, models: List[str]) -> bool:
        self.fetched_frontier_models = models
        self._refresh_top_model_dropdowns()
        self._set_controls_enabled(True)
        self._set_status(f"Fetched {len(models)} models from OpenAI-compatible provider.")
        return False

    def _on_frontier_models_fetch_failed(self, error: str) -> bool:
        self._set_controls_enabled(True)
        self._set_status(f"Model fetch failed: {error}")
        return False

    def _try_autoload_collection(self) -> None:
        self._set_collection_loading(True, "Loading collection from local datastore...")
        threading.Thread(target=self._autoload_collection_worker, daemon=True).start()

    def _autoload_collection_worker(self) -> None:
        try:
            if self.collection.load_active_collection():
                GLib.idle_add(
                    self._on_collection_loaded,
                    "Collection loaded from datastore.",
                )
                return

            candidates = [
                self.collections_dir / "collection.csv",
                self.collections_dir / "mtg.csv",
                self.workspace_dir / "collection.csv",
                self.workspace_dir / "mtg.csv",
            ]
            for candidate in candidates:
                if not candidate.exists():
                    continue
                self.collection.import_csv(candidate)
                GLib.idle_add(
                    self._on_collection_loaded,
                    f"Collection imported from {candidate.name} and loaded from datastore.",
                )
                return
            GLib.idle_add(self._on_collection_load_failed, "No datastore or collection CSV found.")
        except Exception as err:
            GLib.idle_add(self._on_collection_load_failed, str(err))

    def _on_load_collection_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative(
            title="Choose collection CSV",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Load",
            cancel_label="Cancel",
        )
        dialog.connect("response", self._on_collection_dialog_response)
        dialog.show()

    def _on_collection_dialog_response(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            selected = dialog.get_file()
            if selected:
                self._load_collection(Path(selected.get_path()))
        dialog.destroy()

    def _load_collection(self, path: Path) -> None:
        self._set_collection_loading(True, f"Importing {path.name} into datastore...")
        self._set_status(f"Importing {path.name}...")
        threading.Thread(target=self._load_collection_worker, args=(path,), daemon=True).start()

    def _load_collection_worker(self, path: Path) -> None:
        try:
            self.collection.import_csv(path)
            GLib.idle_add(
                self._on_collection_loaded,
                f"Imported {path.name} into datastore and loaded collection.",
            )
        except Exception as err:
            GLib.idle_add(self._on_collection_load_failed, f"Could not import collection file: {err}")

    def _on_collection_loaded(self, status_message: str) -> bool:
        self._set_collection_loading(False, "")
        self.collection_type_filter_force_all_once = True
        self._update_collection_labels()
        self._populate_collection_list()
        self._refresh_saved_decks()
        self._signal_collection_prefetch()
        self._refresh_scryfall_status_display()
        self._set_status(status_message)
        return False

    def _on_collection_load_failed(self, error_message: str) -> bool:
        self._set_collection_loading(False, "")
        self._set_status(error_message)
        return False

    def _update_collection_labels(self) -> None:
        if self.collection.path is None:
            label = "Collection: not loaded"
        else:
            source = self.collection.source_label or self.collection.path.name
            label = f"Collection: {source} ({len(self.collection.cards)} unique cards) [datastore]"
        self.collection_label.set_text(label)
        if self.collection_dialog_label is not None:
            self.collection_dialog_label.set_text(label)

    def _on_save_settings_clicked(self, _button: Gtk.Button) -> None:
        provider_key = self._selected_provider_key()
        self.config.set("provider_key", provider_key)

        if self.settings_cursor_key_entry is not None:
            self.config.set("cursor_api_key", self.settings_cursor_key_entry.get_text())
        self.config.set("cursor_model", self._effective_cursor_model() or "composer-2.5")

        if self.settings_frontier_key_entry is not None:
            self.config.set("frontier_api_key", self.settings_frontier_key_entry.get_text())
        self.config.set("frontier_model", self._effective_frontier_model() or "gpt-4.1")
        try:
            self.config.save()
            self._set_status("Saved app and connectivity settings.")
        except OSError as err:
            self._set_status(f"Failed to save settings: {err}")

    def _on_test_cursor_clicked(self, _button: Gtk.Button) -> None:
        self._start_connection_test("cursor")

    def _on_test_frontier_clicked(self, _button: Gtk.Button) -> None:
        self._start_connection_test("openai")

    def _start_connection_test(self, provider_key: str) -> None:
        label = "Cursor" if provider_key == "cursor" else "OpenAI-compatible"
        self._set_controls_enabled(False)
        self._set_status(f"Testing {label} connection...")
        thread = threading.Thread(target=self._test_connection_worker, args=(provider_key,), daemon=True)
        thread.start()

    def _test_connection_worker(self, provider_key: str) -> None:
        try:
            api_key, model = self._selected_provider_config(provider_key)
            message = self.clients[provider_key].test_connection(api_key=api_key, model=model)
            GLib.idle_add(self._on_test_connection_finished, message, True)
        except Exception as err:
            GLib.idle_add(self._on_test_connection_finished, str(err), False)

    def _on_test_connection_finished(self, message: str, success: bool) -> bool:
        self._set_controls_enabled(True)
        self._set_status(("Connection OK: " if success else "Connection failed: ") + message)
        return False

    def _on_build_clicked(self, _button: Gtk.Button) -> None:
        self._ensure_builder_dialog()
        commander = (
            self.builder_commander_entry.get_text().strip()
            if self.builder_commander_entry is not None
            else ""
        )
        theme = self.builder_theme_entry.get_text().strip() if self.builder_theme_entry is not None else ""
        bracket = (
            self.builder_bracket_entry.get_text().strip()
            if self.builder_bracket_entry is not None
            else "3"
        ) or "3"

        if not commander:
            self._set_status("Commander is required.")
            return
        if not theme:
            self._set_status("Theme is required.")
            return
        deck_name = (
            self.builder_deck_name_entry.get_text().strip()
            if self.builder_deck_name_entry is not None
            else ""
        )
        if not deck_name:
            deck_name = f"{commander} {theme}"
        self.pending_deck_name = deck_name

        prompt_buffer = self.builder_prompt_view.get_buffer() if self.builder_prompt_view is not None else None
        if prompt_buffer is None:
            self._set_status("Deck builder inputs are unavailable.")
            return
        extra = prompt_buffer.get_text(
            prompt_buffer.get_start_iter(),
            prompt_buffer.get_end_iter(),
            True,
        ).strip()

        provider_key = self._selected_provider_key()
        provider_name = self.clients[provider_key].provider_label
        self._set_controls_enabled(False)
        build_start_message = f"Building deck with {provider_name}..."
        self._set_status(build_start_message)
        self._set_builder_hud(True, build_start_message)

        thread = threading.Thread(
            target=self._build_deck_worker,
            args=(provider_key, commander, theme, bracket, extra),
            daemon=True,
        )
        thread.start()

    def _build_deck_worker(
        self,
        provider_key: str,
        commander: str,
        theme: str,
        bracket: str,
        extra: str,
    ) -> None:
        try:
            api_key, model = self._selected_provider_config(provider_key)
            GLib.idle_add(self._on_build_progress, "Preparing deck generation request...")
            status_msg = "Deck built successfully."
            try:
                deck = self.clients[provider_key].build_deck(
                    self.collection,
                    commander=commander,
                    theme=theme,
                    bracket_target=bracket,
                    extra_prompt=extra,
                    api_key=api_key,
                    model=model,
                    status_callback=lambda message: GLib.idle_add(self._on_build_progress, message),
                )
            except Exception as err:
                if provider_key == "offline":
                    raise
                deck = self.clients["offline"].build_deck(
                    self.collection,
                    commander=commander,
                    theme=theme,
                    bracket_target=bracket,
                    extra_prompt=extra,
                    api_key="",
                    model="",
                    status_callback=lambda message: GLib.idle_add(self._on_build_progress, message),
                )
                status_msg = f"AI provider failed ({err}); built deck using offline mode."
            GLib.idle_add(self._on_deck_ready, deck, status_msg)
        except Exception as err:
            GLib.idle_add(self._on_deck_failed, str(err))

    def _on_deck_ready(self, deck: List[DeckCard], status_msg: str) -> bool:
        self.deck_cards = deck
        self._set_controls_enabled(True)
        self._set_builder_hud(False, "")
        save_path = self._save_current_deck(self.pending_deck_name)
        if save_path is not None:
            self._refresh_saved_decks(save_path)
            if self.builder_dialog is not None:
                self.builder_dialog.hide()
            self.content_tabs.set_current_page(1)
            final_status = f"{status_msg} Auto-saved to {save_path}."
            self._set_status(final_status)
            self._show_build_complete_prompt(final_status)
        else:
            self._set_status(f"{status_msg} Auto-save failed.")
        return False

    def _on_deck_failed(self, error: str) -> bool:
        self._set_controls_enabled(True)
        self._set_builder_hud(False, "")
        self._set_status(f"Deck build failed: {error}")
        return False

    def _on_build_progress(self, message: str) -> bool:
        self._set_status(message)
        self._set_builder_hud(True, message)
        return False

    def _set_builder_hud(self, visible: bool, message: str) -> None:
        if self.builder_progress_box is not None:
            self.builder_progress_box.set_visible(visible)
        if self.builder_progress_label is not None:
            self.builder_progress_label.set_text(message)
        if self.builder_progress_spinner is not None:
            if visible:
                self.builder_progress_spinner.start()
            else:
                self.builder_progress_spinner.stop()

    def _clear_listbox(self, listbox: Gtk.ListBox) -> None:
        row = listbox.get_first_child()
        while row is not None:
            next_row = row.get_next_sibling()
            listbox.remove(row)
            row = next_row

    def _append_divider_row(self, listbox: Gtk.ListBox, label_text: str) -> None:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{label_text}</b>")
        row.set_child(label)
        listbox.append(row)

    def _populate_collection_list(self) -> None:
        self.collection_render_token += 1
        render_token = self.collection_render_token
        self.collection_display_rows = self.collection.as_display_rows()
        self._schedule_collection_type_filter_refresh(render_token)
        if self._is_collection_grid_mode():
            self._populate_collection_grid(render_token)
            self._update_prefetch_priority_cards()
            return
        if self.collection_stack is not None:
            self.collection_stack.set_visible_child_name("list")
        if self.collection_group_dropdown.get_selected() == 1:
            self.collection_group_render_token += 1
            selected_filter = self._selected_collection_type_filter()
            self._set_status("Grouping collection by card type...")
            self._clear_listbox(self.collection_list)
            self._set_collection_loading(True, "Filtering collection by card type...")
            rows_snapshot = list(self.collection_display_rows)
            threading.Thread(
                target=self._group_collection_by_type_worker,
                args=(render_token, self.collection_group_render_token, rows_snapshot, selected_filter),
                daemon=True,
            ).start()
            self._update_prefetch_priority_cards()
            return
        self._set_collection_loading(False, "")
        self._render_collection_by_name()
        self._update_prefetch_priority_cards()

    def _render_collection_by_name(self) -> None:
        entries: List[Dict[str, object]] = []
        for name, qty, meta in self.collection_display_rows:
            entries.append({"kind": "card", "name": name, "qty": qty, "meta": meta})
        self._begin_collection_list_render(self.collection_render_token, entries)

    def _populate_collection_grid(self, render_token: int) -> None:
        if self.collection_stack is not None:
            self.collection_stack.set_visible_child_name("grid")
        if self.collection_grid is None:
            return
        self._clear_flowbox(self.collection_grid)
        self._set_collection_loading(True, "Preparing filtered grid...")

        group_by_type = self.collection_group_dropdown.get_selected() == 1
        selected_filter = self._selected_collection_type_filter()
        rows_snapshot = list(self.collection_display_rows)
        threading.Thread(
            target=self._prepare_collection_grid_rows_worker,
            args=(render_token, rows_snapshot, group_by_type, selected_filter),
            daemon=True,
        ).start()

    def _prepare_collection_grid_rows_worker(
        self,
        render_token: int,
        rows_snapshot: List[Tuple[str, int, Dict[str, str]]],
        group_by_type: bool,
        selected_filter: str,
    ) -> None:
        grouped_rows: List[Tuple[str, int, Dict[str, str]]] = []
        missing_type_count = 0
        if group_by_type:
            groups: Dict[str, List[Tuple[str, int, Dict[str, str]]]] = {label: [] for label in CARD_TYPE_ORDER}
            for name, qty, meta in rows_snapshot:
                category = self.image_cache.get_card_type_category_cached(name)
                if category is None:
                    missing_type_count += 1
                    category = "Other"
                groups[category if category in groups else "Other"].append((name, qty, meta))
            labels_to_show = CARD_TYPE_ORDER if selected_filter == "All Types" else [selected_filter]
            for label in labels_to_show:
                grouped_rows.extend(sorted(groups.get(label, []), key=lambda row: row[0].lower()))
        else:
            grouped_rows = sorted(rows_snapshot, key=lambda row: row[0].lower())
        GLib.idle_add(
            self._on_collection_grid_rows_prepared,
            render_token,
            grouped_rows,
            group_by_type,
            selected_filter,
            missing_type_count,
        )

    def _on_collection_grid_rows_prepared(
        self,
        render_token: int,
        grid_rows: List[Tuple[str, int, Dict[str, str]]],
        group_by_type: bool,
        selected_filter: str,
        missing_type_count: int,
    ) -> bool:
        if render_token != self.collection_render_token:
            return False
        self.collection_grid_render_token += 1
        grid_render_token = self.collection_grid_render_token
        self.collection_grid_rows = grid_rows
        self.collection_grid_next_index = 0
        self.collection_grid_target_index = 0
        self.collection_grid_append_in_progress = False
        self.collection_grid_complete_sent = False
        self.collection_grid_visible_start_index = 0
        self.collection_grid_visible_end_index = min(len(self.collection_grid_rows), 24)
        self.collection_thumbnail_queue = queue.Queue()
        self._set_collection_loading(False, "")
        total_unique = len(self.collection_display_rows)
        if group_by_type:
            if selected_filter != "All Types":
                if grid_rows:
                    self._set_status(
                        f"Collection grid loading ({selected_filter}: {len(grid_rows)}/{total_unique} unique cards)..."
                    )
                else:
                    self._set_status(f"No cards found for type filter: {selected_filter}.")
            else:
                if missing_type_count > 0:
                    self._set_status(
                        f"Collection grid loading (grouped by card type, fast mode). Refining {missing_type_count} uncached card types..."
                    )
                else:
                    self._set_status("Collection grid loading (grouped by card type)...")
            if missing_type_count > 0:
                self._signal_collection_prefetch()
        else:
            self._set_status("Collection grid loading...")
        self._request_collection_grid_batch(grid_render_token)
        self._update_prefetch_priority_cards()
        return False

    def _clear_flowbox(self, flowbox: Gtk.FlowBox) -> None:
        child = flowbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            flowbox.remove(child)
            child = next_child

    def _request_collection_grid_batch(self, render_token: int) -> None:
        if render_token != self.collection_grid_render_token:
            return
        if self.collection_grid_append_in_progress:
            return
        if self.collection_grid_next_index >= len(self.collection_grid_rows):
            if not self.collection_grid_complete_sent:
                self.collection_grid_complete_sent = True
                self._set_status("Collection grid ready.")
            return
        self.collection_grid_target_index = min(
            self.collection_grid_next_index + self.collection_grid_batch_size,
            len(self.collection_grid_rows),
        )
        self.collection_grid_append_in_progress = True
        GLib.idle_add(self._append_collection_grid_chunk, render_token)
        self._update_prefetch_priority_cards()

    def _append_collection_grid_chunk(self, render_token: int) -> bool:
        if render_token != self.collection_grid_render_token:
            self.collection_grid_append_in_progress = False
            return False
        if self.collection_grid is None:
            self.collection_grid_append_in_progress = False
            return False
        if self.collection_grid_next_index >= len(self.collection_grid_rows):
            self.collection_grid_append_in_progress = False
            if not self.collection_grid_complete_sent:
                self.collection_grid_complete_sent = True
                self._set_status("Collection grid ready.")
            return False

        start = self.collection_grid_next_index
        end = min(start + self.collection_grid_chunk_size, self.collection_grid_target_index)
        for idx in range(start, end):
            name, qty, meta = self.collection_grid_rows[idx]
            thumb_stack = Gtk.Stack()
            thumb_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            thumb_stack.set_size_request(140, 195)

            loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            loading_box.set_halign(Gtk.Align.CENTER)
            loading_box.set_valign(Gtk.Align.CENTER)
            loading_box.add_css_class("thumb-skeleton")

            missing_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            missing_box.set_halign(Gtk.Align.CENTER)
            missing_box.set_valign(Gtk.Align.CENTER)
            missing_box.add_css_class("thumb-missing")
            missing_box.append(Gtk.Label(label="No image"))

            picture = Gtk.Picture()
            picture.set_size_request(140, 195)
            picture.set_can_shrink(True)
            thumb_stack.add_named(loading_box, "loading")
            thumb_stack.add_named(picture, "image")
            thumb_stack.add_named(missing_box, "missing")
            thumb_stack.set_visible_child_name("loading")
            caption = Gtk.Label(xalign=0)
            caption.set_wrap(True)
            caption.set_max_width_chars(18)
            caption.set_text(f"{qty}x {name}")

            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            tile.append(thumb_stack)
            tile.append(caption)

            button = Gtk.Button()
            button.set_child(tile)
            detail = (
                f"Source: Collection | Quantity: {qty} | "
                f"Set: {meta.get('set_code', '')} {meta.get('set_name', '')} | "
                f"Collector: {meta.get('collector_number', '')} | "
                f"Rarity: {meta.get('rarity', '')}"
            )
            button.connect("clicked", self._on_collection_thumbnail_clicked, name, detail, meta)

            child = Gtk.FlowBoxChild()
            child.set_child(button)
            self.collection_grid.append(child)
            if self.collection_thumbnail_queue is not None:
                self.collection_thumbnail_queue.put((render_token, thumb_stack, picture, name, meta))

        self.collection_grid_next_index = end
        self._ensure_collection_thumbnail_worker(render_token)
        if self.collection_grid_next_index < self.collection_grid_target_index:
            return True
        self.collection_grid_append_in_progress = False
        if self.collection_grid_next_index >= len(self.collection_grid_rows) and not self.collection_grid_complete_sent:
            self.collection_grid_complete_sent = True
            self._set_status("Collection grid ready.")
        return False

    def _ensure_collection_thumbnail_worker(self, render_token: int) -> None:
        worker = self.collection_thumbnail_worker
        if (
            worker is not None
            and worker.is_alive()
            and self.collection_thumbnail_worker_token == render_token
        ):
            return
        self.collection_thumbnail_worker = threading.Thread(
            target=self._collection_thumbnail_worker,
            args=(render_token,),
            daemon=True,
        )
        self.collection_thumbnail_worker_token = render_token
        self.collection_thumbnail_worker.start()

    def _collection_thumbnail_worker(self, render_token: int) -> None:
        while render_token == self.collection_grid_render_token:
            if self.collection_thumbnail_queue is None:
                return
            try:
                job_token, thumb_stack, picture, card_name, meta = self.collection_thumbnail_queue.get(
                    timeout=0.25
                )
            except queue.Empty:
                if (
                    render_token == self.collection_grid_render_token
                    and self.collection_grid_next_index >= len(self.collection_grid_rows)
                    and not self.collection_grid_complete_sent
                ):
                    GLib.idle_add(self._on_collection_thumbnail_batch_complete, render_token)
                continue
            if job_token != self.collection_grid_render_token:
                continue
            try:
                image_path, _exact_match = self.image_cache.get_or_fetch_with_preference(
                    card_name=card_name,
                    set_code=meta.get("set_code", ""),
                    collector_number=meta.get("collector_number", ""),
                )
            except Exception:
                image_path = None
            if image_path is None:
                GLib.idle_add(self._on_collection_thumbnail_failed, thumb_stack, job_token)
                continue
            GLib.idle_add(
                self._on_collection_thumbnail_ready,
                thumb_stack,
                picture,
                image_path,
                render_token,
                card_name,
                meta,
            )

    def _on_collection_thumbnail_ready(
        self,
        thumb_stack: Gtk.Stack,
        picture: Gtk.Picture,
        image_path: Path,
        render_token: int,
        card_name: str,
        meta: Dict[str, str],
    ) -> bool:
        if render_token != self.collection_grid_render_token:
            return False
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(image_path), 140, 195, True)
            picture.set_pixbuf(pixbuf)
            thumb_stack.set_visible_child_name("image")
        except Exception:
            thumb_stack.set_visible_child_name("loading")
            threading.Thread(
                target=self._repair_collection_thumbnail_worker,
                args=(render_token, thumb_stack, picture, card_name, meta),
                daemon=True,
            ).start()
            return False
        return False

    def _on_collection_thumbnail_failed(self, thumb_stack: Gtk.Stack, render_token: int) -> bool:
        if render_token != self.collection_grid_render_token:
            return False
        thumb_stack.set_visible_child_name("missing")
        return False

    def _repair_collection_thumbnail_worker(
        self,
        render_token: int,
        thumb_stack: Gtk.Stack,
        picture: Gtk.Picture,
        card_name: str,
        meta: Dict[str, str],
    ) -> None:
        if render_token != self.collection_grid_render_token:
            return
        set_code = meta.get("set_code", "")
        collector_number = meta.get("collector_number", "")
        self.image_cache.repair_cached_image(card_name, set_code=set_code, collector_number=collector_number)
        image_path, _exact_match = self.image_cache.get_or_fetch_with_preference(
            card_name=card_name,
            set_code=set_code,
            collector_number=collector_number,
        )
        if image_path is None:
            GLib.idle_add(self._on_collection_thumbnail_failed, thumb_stack, render_token)
            return
        GLib.idle_add(
            self._on_collection_thumbnail_repair_ready,
            render_token,
            thumb_stack,
            picture,
            image_path,
        )

    def _on_collection_thumbnail_repair_ready(
        self,
        render_token: int,
        thumb_stack: Gtk.Stack,
        picture: Gtk.Picture,
        image_path: Path,
    ) -> bool:
        if render_token != self.collection_grid_render_token:
            return False
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(image_path), 140, 195, True)
            picture.set_pixbuf(pixbuf)
            thumb_stack.set_visible_child_name("image")
            self._set_status(f"Repaired thumbnail image for {image_path.stem}.")
        except Exception:
            thumb_stack.set_visible_child_name("missing")
        return False

    def _on_collection_thumbnail_batch_complete(self, render_token: int) -> bool:
        if render_token != self.collection_grid_render_token:
            return False
        self.collection_grid_complete_sent = True
        self._set_status("Collection thumbnails ready.")
        return False

    def _on_collection_thumbnail_clicked(
        self,
        _button: Gtk.Button,
        name: str,
        detail: str,
        meta: Dict[str, str],
    ) -> None:
        self._show_card_preview(name, detail, meta)

    def _group_collection_by_type_worker(
        self,
        collection_render_token: int,
        group_render_token: int,
        rows_snapshot: List[Tuple[str, int, Dict[str, str]]],
        selected_filter: str,
    ) -> None:
        groups: Dict[str, List[Tuple[str, int, Dict[str, str]]]] = {label: [] for label in CARD_TYPE_ORDER}
        missing_type_count = 0
        for name, qty, meta in rows_snapshot:
            category = self.image_cache.get_card_type_category_cached(name)
            if category is None:
                missing_type_count += 1
                category = "Other"
            groups[category if category in groups else "Other"].append((name, qty, meta))
        if selected_filter == "All Types":
            grouped = [(label, sorted(groups[label], key=lambda x: x[0])) for label in CARD_TYPE_ORDER if groups[label]]
        else:
            selected_cards = sorted(groups.get(selected_filter, []), key=lambda x: x[0])
            grouped = [(selected_filter, selected_cards)] if selected_cards else []
        GLib.idle_add(
            self._on_collection_type_grouped_ready,
            grouped,
            collection_render_token,
            group_render_token,
            missing_type_count,
            selected_filter,
        )

    def _on_collection_type_grouped_ready(
        self,
        grouped: List[Tuple[str, List[Tuple[str, int, Dict[str, str]]]]],
        collection_render_token: int,
        group_render_token: int,
        missing_type_count: int,
        selected_filter: str,
    ) -> bool:
        if collection_render_token != self.collection_render_token:
            return False
        if group_render_token != self.collection_group_render_token:
            return False
        self._set_collection_loading(False, "")
        entries: List[Dict[str, object]] = []
        for label, cards in grouped:
            entries.append({"kind": "divider", "label": label})
            for name, qty, meta in cards:
                entries.append({"kind": "card", "name": name, "qty": qty, "meta": meta})
        self._begin_collection_list_render(collection_render_token, entries)
        if not grouped and selected_filter != "All Types":
            self._set_status(f"No cards found for type filter: {selected_filter}.")
            self._update_prefetch_priority_cards()
            return False
        visible_cards = sum(len(cards) for _label, cards in grouped)
        total_unique = len(self.collection_display_rows)
        if missing_type_count > 0:
            if selected_filter != "All Types":
                self._set_status(
                    f"Showing {selected_filter}: {visible_cards}/{total_unique} unique cards (fast mode). Refining {missing_type_count} uncached card types in background..."
                )
            else:
                self._set_status(
                    f"Collection grouped by card type (fast mode). Refining {missing_type_count} uncached card types in background..."
                )
            self._signal_collection_prefetch()
        else:
            if selected_filter != "All Types":
                self._set_status(f"Showing {selected_filter}: {visible_cards}/{total_unique} unique cards.")
            else:
                self._set_status("Collection grouped by card type.")
        self._update_prefetch_priority_cards()
        return False

    def _refresh_collection_type_grouping_if_active(self) -> bool:
        if self.collection_group_dropdown.get_selected() == 1 and not self._is_collection_grid_mode():
            self._populate_collection_list()
        elif self.collection_group_dropdown.get_selected() == 1:
            self._schedule_collection_type_filter_refresh(self.collection_render_token)
        return False

    def _schedule_collection_type_filter_refresh(self, render_token: int) -> None:
        is_type_mode = self.collection_group_dropdown.get_selected() == 1
        if self.collection_type_filter_box is not None:
            self.collection_type_filter_box.set_visible(is_type_mode)
        if self.collection_type_filter_dropdown is None:
            return
        selected_type = self._selected_collection_type_filter()
        refresh_token = self.collection_type_filter_refresh_token + 1
        self.collection_type_filter_refresh_token = refresh_token
        rows_snapshot = list(self.collection_display_rows)
        threading.Thread(
            target=self._collection_type_filter_options_worker,
            args=(refresh_token, render_token, rows_snapshot, selected_type, is_type_mode),
            daemon=True,
        ).start()

    def _collection_type_filter_options_worker(
        self,
        refresh_token: int,
        render_token: int,
        rows_snapshot: List[Tuple[str, int, Dict[str, str]]],
        selected_type: str,
        is_type_mode: bool,
    ) -> None:
        type_set = set()
        for name, _qty, _meta in rows_snapshot:
            type_set.add(self.image_cache.get_card_type_category_cached(name) or "Other")
        labels = [label for label in CARD_TYPE_ORDER if label in type_set]
        options = ["All Types"] + labels
        GLib.idle_add(
            self._on_collection_type_filter_options_ready,
            refresh_token,
            render_token,
            options,
            selected_type,
            is_type_mode,
        )

    def _on_collection_type_filter_options_ready(
        self,
        refresh_token: int,
        render_token: int,
        options: List[str],
        selected_type: str,
        is_type_mode: bool,
    ) -> bool:
        if refresh_token != self.collection_type_filter_refresh_token:
            return False
        if render_token != self.collection_render_token:
            return False
        if self.collection_type_filter_dropdown is None:
            return False
        self.collection_type_filter_options = options
        self.collection_type_filter_updating = True
        self.collection_type_filter_dropdown.set_model(Gtk.StringList.new(options))
        if self.collection_type_filter_force_all_once and "All Types" in options:
            self.collection_type_filter_dropdown.set_selected(options.index("All Types"))
            self.collection_type_filter_force_all_once = False
        elif selected_type in options:
            self.collection_type_filter_dropdown.set_selected(options.index(selected_type))
        else:
            self.collection_type_filter_dropdown.set_selected(0)
        self.collection_type_filter_dropdown.set_sensitive(is_type_mode and len(options) > 1)
        self.collection_type_filter_updating = False
        return False

    def _selected_collection_type_filter(self) -> str:
        if self.collection_type_filter_dropdown is None:
            return "All Types"
        selected = self.collection_type_filter_dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            return "All Types"
        if selected < 0 or selected >= len(self.collection_type_filter_options):
            return "All Types"
        return self.collection_type_filter_options[selected]

    def _on_collection_type_filter_selected(self, _dropdown: Gtk.DropDown, _pspec: object) -> None:
        if self.collection_type_filter_updating:
            return
        self.collection_type_filter_force_all_once = False
        if self.collection_group_dropdown.get_selected() == 1:
            self._populate_collection_list()

    def _begin_collection_list_render(
        self,
        render_token: int,
        entries: List[Dict[str, object]],
    ) -> None:
        self.collection_list_render_token = render_token
        self.collection_list_render_entries = entries
        self.collection_list_render_index = 0
        self._clear_listbox(self.collection_list)
        self.collection_rows = []
        GLib.idle_add(self._append_collection_list_chunk, render_token)

    def _append_collection_list_chunk(self, render_token: int) -> bool:
        if render_token != self.collection_render_token:
            return False
        if render_token != self.collection_list_render_token:
            return False
        start = self.collection_list_render_index
        end = min(start + self.collection_list_chunk_size, len(self.collection_list_render_entries))
        for idx in range(start, end):
            entry = self.collection_list_render_entries[idx]
            kind = str(entry.get("kind", ""))
            if kind == "divider":
                label = str(entry.get("label", ""))
                self._append_divider_row(self.collection_list, label)
                self.collection_rows.append(None)
                continue
            name = str(entry.get("name", ""))
            qty = int(entry.get("qty", 1))
            meta = entry.get("meta", {})
            if not isinstance(meta, dict):
                meta = {}
            item_row = Gtk.ListBoxRow()
            item_row.set_child(Gtk.Label(label=f"{qty}x {name}", xalign=0))
            self.collection_list.append(item_row)
            self.collection_rows.append((name, qty, meta))
        self.collection_list_render_index = end
        if end < len(self.collection_list_render_entries):
            return True
        return False

    def _collection_grid_row_pitch(self) -> float:
        # Prefer measured geometry to avoid category jump undershoot/overshoot.
        if self.collection_grid is not None:
            first_child = self.collection_grid.get_child_at_index(0)
            if first_child is not None:
                child_height = float(first_child.get_allocated_height())
                if child_height > 0:
                    return child_height + float(self.collection_grid.get_row_spacing())
        return 235.0

    def _update_prefetch_priority_cards(self) -> None:
        rows = self.collection_display_rows
        if not rows:
            with self.collection_prefetch_priority_lock:
                self.collection_prefetch_priority_cards = []
            return

        prefetch_cap = 300
        ordered_rows: List[Tuple[str, int, Dict[str, str]]]
        if self._is_collection_grid_mode() and self.collection_grid_rows:
            start = max(0, min(self.collection_grid_visible_start_index, len(self.collection_grid_rows)))
            end = max(start, min(self.collection_grid_visible_end_index, len(self.collection_grid_rows)))
            visible_rows = self.collection_grid_rows[start:end]
            if len(visible_rows) >= prefetch_cap:
                ordered_rows = visible_rows[:prefetch_cap]
            else:
                remaining = prefetch_cap - len(visible_rows)
                ordered_rows = visible_rows + self.collection_grid_rows[:start][:remaining]
                if len(ordered_rows) < prefetch_cap:
                    ordered_rows += self.collection_grid_rows[end : end + (prefetch_cap - len(ordered_rows))]
        else:
            ordered_rows = rows[:prefetch_cap]

        prioritized = [(name, dict(meta)) for name, _qty, meta in ordered_rows]
        with self.collection_prefetch_priority_lock:
            self.collection_prefetch_priority_cards = prioritized
        self._signal_collection_prefetch()

    def _get_prefetch_priority_cards_snapshot(self) -> List[Tuple[str, Dict[str, str]]]:
        with self.collection_prefetch_priority_lock:
            if self.collection_prefetch_priority_cards:
                return [(name, dict(meta)) for name, meta in self.collection_prefetch_priority_cards]
        return [(name, dict(meta)) for name, _qty, meta in self.collection.as_display_rows()]

    def _refresh_saved_decks(self, preferred_path: Optional[Path] = None) -> None:
        self.generated_decks_dir.mkdir(parents=True, exist_ok=True)
        self.saved_deck_files = sorted(self.generated_decks_dir.glob("*.csv"))
        deck_names = [path.name for path in self.saved_deck_files]
        self.saved_decks_model = Gtk.StringList.new(deck_names)
        self.saved_decks_dropdown.set_model(self.saved_decks_model)
        if deck_names:
            selected_index = 0
            if preferred_path is not None:
                for idx, path in enumerate(self.saved_deck_files):
                    if path.resolve() == preferred_path.resolve():
                        selected_index = idx
                        break
            self.saved_decks_dropdown.set_selected(selected_index)
            self._load_saved_deck(self.saved_deck_files[selected_index])
        else:
            self.saved_deck_cards = []
            self.saved_deck_rows = []
            self._clear_listbox(self.saved_decks_list)

    def _load_saved_deck(self, deck_path: Path) -> None:
        try:
            rows = list(csv.DictReader(deck_path.open("r", encoding="utf-8", newline="")))
        except Exception as err:
            self._set_status(f"Failed to read generated deck {deck_path.name}: {err}")
            return
        cards: List[DeckCard] = []
        for row in rows:
            name = (row.get("Name") or "").strip().strip('"')
            section = (row.get("Section") or "Nonland").strip() or "Nonland"
            if not name:
                continue
            try:
                quantity = int((row.get("Quantity") or "1").strip())
            except ValueError:
                quantity = 1
            cards.append(DeckCard(section=section, name=name, quantity=quantity))
        self.saved_deck_cards = cards
        self._populate_saved_deck_list()

    def _populate_saved_deck_list(self) -> None:
        if self.saved_decks_group_dropdown.get_selected() == 1:
            self._set_status("Grouping generated deck by card type...")
            self._clear_listbox(self.saved_decks_list)
            threading.Thread(target=self._group_saved_deck_by_type_worker, daemon=True).start()
            return
        self._render_saved_deck_plain()

    def _render_saved_deck_plain(self) -> None:
        self._clear_listbox(self.saved_decks_list)
        self.saved_deck_rows = []
        for card in self.saved_deck_cards:
            item_row = Gtk.ListBoxRow()
            item_row.set_child(Gtk.Label(label=f"{card.quantity}x {card.name} [{card.section}]", xalign=0))
            self.saved_decks_list.append(item_row)
            self.saved_deck_rows.append(card)

    def _group_saved_deck_by_type_worker(self) -> None:
        groups: Dict[str, List[DeckCard]] = {label: [] for label in CARD_TYPE_ORDER}
        for card in self.saved_deck_cards:
            category = "Land" if card.section.lower() == "land" else self.image_cache.get_card_type_category(card.name)
            groups[category if category in groups else "Other"].append(card)
        grouped = [(label, groups[label]) for label in CARD_TYPE_ORDER if groups[label]]
        GLib.idle_add(self._on_saved_deck_type_grouped_ready, grouped)

    def _on_saved_deck_type_grouped_ready(self, grouped: List[Tuple[str, List[DeckCard]]]) -> bool:
        self._clear_listbox(self.saved_decks_list)
        self.saved_deck_rows = []
        for label, cards in grouped:
            self._append_divider_row(self.saved_decks_list, label)
            self.saved_deck_rows.append(None)
            for card in cards:
                item_row = Gtk.ListBoxRow()
                item_row.set_child(Gtk.Label(label=f"{card.quantity}x {card.name} [{card.section}]", xalign=0))
                self.saved_decks_list.append(item_row)
                self.saved_deck_rows.append(card)
        self._set_status("Generated deck grouped by card type.")
        return False

    def _save_current_deck(self, deck_name: str) -> Optional[Path]:
        if not self.deck_cards:
            return None
        self.generated_decks_dir.mkdir(parents=True, exist_ok=True)
        save_path = choose_generated_deck_path(self.generated_decks_dir, deck_name)
        try:
            with save_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Section", "Name", "Quantity"])
                for card in self.deck_cards:
                    writer.writerow([card.section, card.name, card.quantity])
            return save_path
        except Exception as err:
            self._set_status(f"Save failed: {err}")
            return None

    def _on_collection_selected(self, _listbox: Gtk.ListBox, row: Optional[Gtk.ListBoxRow]) -> None:
        if row is None:
            return
        index = row.get_index()
        if index < 0 or index >= len(self.collection_rows):
            return
        selected = self.collection_rows[index]
        if selected is None:
            return
        name, qty, meta = selected
        detail = (
            f"Source: Collection | Quantity: {qty} | "
            f"Set: {meta.get('set_code', '')} {meta.get('set_name', '')} | "
            f"Collector: {meta.get('collector_number', '')} | "
            f"Rarity: {meta.get('rarity', '')}"
        )
        self._show_card_preview(name, detail, meta)

    def _on_saved_deck_changed(self, _dropdown: Gtk.DropDown, _pspec: object) -> None:
        idx = self.saved_decks_dropdown.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return
        if idx < 0 or idx >= len(self.saved_deck_files):
            return
        self._load_saved_deck(self.saved_deck_files[idx])

    def _on_refresh_saved_decks_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_saved_decks()
        self._set_status("Refreshed generated deck list.")

    def _on_copy_generated_deck_clicked(self, _button: Gtk.Button) -> None:
        if not self.saved_deck_cards:
            self._set_status("No generated deck is loaded to copy.")
            return
        selected_idx = self.saved_decks_dropdown.get_selected()
        if selected_idx == Gtk.INVALID_LIST_POSITION or selected_idx >= len(self.saved_deck_files):
            self._set_status("Select a generated deck file first.")
            return

        csv_text = self._build_generated_deck_export_text(self.saved_deck_cards)
        display = Gdk.Display.get_default()
        if display is None:
            self._set_status("Clipboard unavailable on this display.")
            return
        clipboard = display.get_clipboard()
        clipboard.set(csv_text)
        self._set_status(
            f"Copied {len(self.saved_deck_cards)} rows from {self.saved_deck_files[selected_idx].name}."
        )

    def _on_delete_generated_deck_clicked(self, _button: Gtk.Button) -> None:
        selected_idx = self.saved_decks_dropdown.get_selected()
        if selected_idx == Gtk.INVALID_LIST_POSITION or selected_idx >= len(self.saved_deck_files):
            self._set_status("Select a generated deck file to delete.")
            return

        target = self.saved_deck_files[selected_idx]
        self._show_delete_deck_confirm(target)

    def _show_delete_deck_confirm(self, target: Path) -> None:
        prompt = Gtk.Window(title="Confirm Delete", transient_for=self, modal=True)
        prompt.set_default_size(420, 160)
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_margin_start(12)
        container.set_margin_end(12)
        container.set_margin_top(12)
        container.set_margin_bottom(12)
        prompt.set_child(container)

        label = Gtk.Label(xalign=0)
        label.set_wrap(True)
        label.set_text(
            "Delete this generated deck?\n\n"
            f"{target.name}\n\n"
            "This only removes the deck file and does not remove image cache."
        )
        container.append(label)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)
        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", lambda _btn: self._cancel_delete_generated_deck(prompt))
        delete_button = Gtk.Button(label="Delete")
        delete_button.connect("clicked", lambda _btn: self._confirm_delete_generated_deck(prompt, target))
        buttons.append(cancel_button)
        buttons.append(delete_button)
        container.append(buttons)
        prompt.present()

    def _cancel_delete_generated_deck(self, prompt: Gtk.Window) -> None:
        prompt.close()
        self._set_status("Deck deletion canceled.")

    def _confirm_delete_generated_deck(self, prompt: Gtk.Window, target: Path) -> None:
        prompt.close()
        try:
            target.unlink()
        except Exception as err:
            self._set_status(f"Failed to delete {target.name}: {err}")
            return

        self.saved_deck_cards = []
        self.saved_deck_rows = []
        self._clear_listbox(self.saved_decks_list)
        self.card_title.set_text("Select a card to preview.")
        self.card_details.set_text("Card details will appear here.")
        self.card_picture.set_paintable(None)
        self.preview_stack.set_visible_child_name("empty")
        self._refresh_saved_decks()
        self._set_status(f"Deleted generated deck {target.name}.")

    def _build_generated_deck_export_text(self, cards: List[DeckCard]) -> str:
        return format_quantity_name_set_lines(cards, self.collection.card_meta)

    def _on_saved_deck_card_selected(self, _listbox: Gtk.ListBox, row: Optional[Gtk.ListBoxRow]) -> None:
        if row is None:
            return
        index = row.get_index()
        if index < 0 or index >= len(self.saved_deck_rows):
            return
        card = self.saved_deck_rows[index]
        if card is None:
            return
        selected_idx = self.saved_decks_dropdown.get_selected()
        deck_name = (
            self.saved_deck_files[selected_idx].name
            if selected_idx != Gtk.INVALID_LIST_POSITION and selected_idx < len(self.saved_deck_files)
            else "unknown deck"
        )
        collection_meta = self.collection.card_meta.get(card.name, {})
        detail = (
            f"Source: {deck_name} | Section: {card.section} | Quantity: {card.quantity} | "
            f"Set: {collection_meta.get('set_code', '')} {collection_meta.get('set_name', '')} | "
            f"Collector: {collection_meta.get('collector_number', '')}"
        )
        self._show_card_preview(card.name, detail, collection_meta)

    def _show_card_preview(self, card_name: str, detail: str, meta: Optional[Dict[str, str]] = None) -> None:
        self.card_title.set_text(card_name)
        self.card_details.set_text(detail)
        self.card_picture.set_paintable(None)
        self.loading_spinner.start()
        self.preview_stack.set_visible_child_name("loading")
        self._set_status(f"Loading image for {card_name}...")
        meta = meta or {}
        threading.Thread(
            target=self._load_card_image_worker,
            args=(card_name, detail, meta, True),
            daemon=True,
        ).start()

    def _on_collection_group_mode_changed(self, _dropdown: Gtk.DropDown, _pspec: object) -> None:
        self.collection_type_filter_force_all_once = True
        self._populate_collection_list()

    def _on_collection_view_mode_changed(self, _dropdown: Gtk.DropDown, _pspec: object) -> None:
        self._populate_collection_list()

    def _is_collection_grid_mode(self) -> bool:
        if self.collection_view_mode_dropdown is None:
            return False
        return self.collection_view_mode_dropdown.get_selected() == 1

    def _on_collection_grid_scroll_changed(self, adjustment: Gtk.Adjustment) -> None:
        if not self._is_collection_grid_mode():
            return
        if self.collection_grid_render_token <= 0:
            return
        estimated_tile_height = self._collection_grid_row_pitch()
        start_row = int(adjustment.get_value() // estimated_tile_height)
        visible_rows = int(adjustment.get_page_size() // estimated_tile_height) + 2
        self.collection_grid_visible_start_index = max(0, start_row * 3)
        self.collection_grid_visible_end_index = min(
            len(self.collection_grid_rows),
            max(self.collection_grid_visible_start_index + 1, (start_row + visible_rows) * 3),
        )
        self._update_prefetch_priority_cards()
        threshold = 900.0
        viewport_bottom = adjustment.get_value() + adjustment.get_page_size()
        if viewport_bottom >= adjustment.get_upper() - threshold:
            self._request_collection_grid_batch(self.collection_grid_render_token)

    def _on_saved_deck_group_mode_changed(self, _dropdown: Gtk.DropDown, _pspec: object) -> None:
        idx = self.saved_decks_dropdown.get_selected()
        if idx != Gtk.INVALID_LIST_POSITION and 0 <= idx < len(self.saved_deck_files):
            # Reload selected file so grouping always refreshes from source data.
            self._load_saved_deck(self.saved_deck_files[idx])
            return
        self._populate_saved_deck_list()

    def _load_card_image_worker(
        self,
        card_name: str,
        detail: str,
        meta: Dict[str, str],
        allow_repair: bool,
    ) -> None:
        set_code = meta.get("set_code", "")
        collector_number = meta.get("collector_number", "")
        try:
            image_path, exact_match = self.image_cache.get_or_fetch_with_preference(
                card_name=card_name,
                set_code=set_code,
                collector_number=collector_number,
            )
        except Exception:
            image_path = None
            exact_match = False
        if image_path is None:
            GLib.idle_add(self._on_image_failed, card_name, detail)
            return
        GLib.idle_add(
            self._on_image_ready,
            image_path,
            card_name,
            detail,
            exact_match,
            set_code,
            collector_number,
            allow_repair,
        )

    def _on_image_ready(
        self,
        image_path: Path,
        card_name: str,
        detail: str,
        exact_match: bool,
        set_code: str,
        collector_number: str,
        allow_repair: bool,
    ) -> bool:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(image_path), 420, 600, True)
            self.card_picture.set_pixbuf(pixbuf)
            self.loading_spinner.stop()
            self.preview_stack.set_visible_child_name("image")
            note = ""
            if set_code and collector_number and not exact_match:
                note = " | Note: image fallback used (set/collector match not found)"
            self.card_details.set_text(detail + note)
            self._set_status(f"Showing {card_name}.")
        except Exception as err:
            if allow_repair:
                self._set_status(f"Image load issue for {card_name}; repairing cache and retrying...")
                threading.Thread(
                    target=self._repair_preview_image_worker,
                    args=(card_name, detail, set_code, collector_number),
                    daemon=True,
                ).start()
            else:
                self._set_status(f"Image render error: {err}")
                self.loading_spinner.stop()
                self.preview_stack.set_visible_child_name("empty")
                self.card_details.set_text(detail + " | Note: image could not be repaired.")
        return False

    def _repair_preview_image_worker(
        self,
        card_name: str,
        detail: str,
        set_code: str,
        collector_number: str,
    ) -> None:
        self.image_cache.repair_cached_image(
            card_name=card_name,
            set_code=set_code,
            collector_number=collector_number,
        )
        image_path, exact_match = self.image_cache.get_or_fetch_with_preference(
            card_name=card_name,
            set_code=set_code,
            collector_number=collector_number,
        )
        if image_path is None:
            GLib.idle_add(self._on_image_failed, card_name, detail)
            return
        GLib.idle_add(
            self._on_image_ready,
            image_path,
            card_name,
            detail,
            exact_match,
            set_code,
            collector_number,
            False,
        )

    def _on_image_failed(self, card_name: str, detail: str) -> bool:
        self.card_picture.set_paintable(None)
        self.loading_spinner.stop()
        self.preview_stack.set_visible_child_name("empty")
        self.card_details.set_text(detail + " | Note: no image could be retrieved.")
        self._set_status(f"No image found for {card_name}.")
        return False

    def _show_build_complete_prompt(self, message: str) -> None:
        prompt = Gtk.Window(title="Deck Generated", transient_for=self, modal=True)
        prompt.set_default_size(460, 180)
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_margin_start(12)
        container.set_margin_end(12)
        container.set_margin_top(12)
        container.set_margin_bottom(12)
        prompt.set_child(container)

        label = Gtk.Label(xalign=0)
        label.set_wrap(True)
        label.set_text(
            "Deck build complete. Showing the generated deck now.\n\n"
            f"{message}"
        )
        container.append(label)

        ok_button = Gtk.Button(label="OK")
        ok_button.set_halign(Gtk.Align.END)
        ok_button.connect("clicked", lambda _btn: prompt.close())
        container.append(ok_button)
        prompt.present()


class DeckBuilderApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.local.CommanderDeckBuilder")

    def do_activate(self) -> None:
        window = self.props.active_window
        if not window:
            window = DeckBuilderWindow(self)
        window.present()
