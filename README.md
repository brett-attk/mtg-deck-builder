# Commander Deck Builder (GTK)

Desktop app for building MTG Commander decks from your own collection, with:

- datastore-backed collection browsing (fast startup after import)
- deck generation (frontier model API key required)
- optional AI providers (required for deck generation)
- Scryfall image caching and background sync
- list and grid collection views with grouping/filtering

## Project Notice

- This is an AI-first driven project.
- It is built primarily for personal use.
- Use of this project is largely unsupported by the repository owner.
- Feature suggestions are always welcome.

## Features

- Import collection CSV once, then run against local datastore
- Browse collection and generated decks with card previews
- Group by card type and filter by specific type
- Progressive thumbnail loading with background image sync
- AI-assisted deck generation with guardrails
- Offline heuristic deck generation fallback

## Offline and AI Requirements

- You can browse your imported collection offline.
- For AI-powered deck building, you must connect to a supported Frontier/OpenAI-compatible model (or another configured supported provider).
- The app also includes an offline heuristic deck builder, but AI quality/features require a supported model connection.

## Repository Layout

- `deck_builder_app.py`: app entrypoint
- `commander_deck_builder/`: core app modules
- `tests/`: unit tests
- `collections/`: local collection CSV import folder
- `generated-decks/`: generated deck CSV output

## Prerequisites

Linux with Python 3.10+ and GTK4 runtime.

### Ubuntu/Debian packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-gi gir1.2-gtk-4.0
```

## Setup

From project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## Configure Providers and Keys

You can run with:

- `Offline Heuristic (No AI)` (default; no key required)
- `Cursor SDK`
- `OpenAI-compatible API` (Frontier or OpenAI-compatible endpoint)

### Option A: Cursor SDK key

```bash
export CURSOR_API_KEY="cursor_..."
export CURSOR_MODEL="composer-2.5"
```

### Option B: Frontier/OpenAI-compatible key

```bash
export FRONTIER_API_KEY="your_api_key"
export FRONTIER_API_BASE="https://api.openai.com/v1"
export FRONTIER_MODEL="gpt-4.1"
```

Notes:

- `OPENAI_API_KEY` is accepted as fallback for the OpenAI-compatible provider.
- Keys can also be entered in-app under **Settings** and are saved to local user config.

### Optional local env file

Use the template:

```bash
cp .env.example .env
```

Then set your values in `.env`, and load them before launch:

```bash
set -a
source .env
set +a
```

## Start the App

```bash
python3 deck_builder_app.py
```

## First-Time Collection Import (Datastore-First)

The app imports CSV data into a local datastore and runs from datastore thereafter.

1. Put your collection CSV in `collections/` (example: `collections/mtg.csv`) or keep it anywhere accessible.
2. Open **Collection Manager**.
3. Click **Load Collection CSV** and select your file.
4. Wait for import HUD/progress to finish.
5. After import, normal operations run against datastore-backed collection data.

On later launches:

- app tries to load active collection directly from datastore first
- CSV file is no longer required for normal app usage once imported

## Typical Usage Flow

1. Open **Settings**
2. Select provider (`offline`, `cursor`, or `openai-compatible`)
3. Enter key/model if needed and test connection
4. Open **Deck Builder**, set commander/theme/bracket, and click **Build Deck**
5. Review generated deck under **Generated Decks**
6. Browse collection cards in list or grid, group/filter by card type

## Data Storage Paths

- App settings: `~/.config/commander-deck-builder/config.json`
- Collection datastore + cache files: `~/.cache/commander-deck-builder/`
- Scryfall images: `~/.cache/commander-deck-builder/images`
- Generated decks: `generated-decks/*.csv`

## Performance/UX Notes

- Heavy collection operations are async to keep UI responsive.
- HUD/spinner indicators appear during long user-triggered actions (import/filter prep).
- Scryfall image sync is rate-limited and runs in background.
- Image coverage status shows progress against full collection size.

## Testing

Run full test suite:

```bash
python3 -m unittest discover -s tests -v
```

## GitHub Safety

- Do not commit real keys or local config.
- `.gitignore` excludes:
  - `.venv/`
  - collection/deck CSV runtime data
  - local `.env*` files (except `.env.example`)
- Keep real secrets in environment variables or local config only.

## Troubleshooting

- `ModuleNotFoundError: cursor_sdk`: reinstall deps with `python3 -m pip install -r requirements.txt`
- GTK import failure: verify `python3-gi` and `gir1.2-gtk-4.0` installed
- API connection failures: validate key/model/provider in **Settings**
- Missing thumbnails: background sync may still be running; status bar shows Scryfall activity and coverage
