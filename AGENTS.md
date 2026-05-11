# Agents

This repository is a Python CLI for searching an Audiobookshelf server,
downloading selected audiobook items into `downloads/`, and optionally

## Workflow

- Use `uv` for dependency and command execution.
- Use package-manager commands for dependencies instead of editing lock files by hand.
- Keep changes small and direct. Do not add broad abstractions for hypothetical future behavior.
- Preserve existing local worktree changes unless explicitly told to replace them.
- Use project-relative paths in docs and comments.

## Commands

- Search and manage the queue with the TUI:

  ```sh
  uv run audiobookshelf-sync search
  ```

- Download queued items:

  ```sh
  uv run audiobookshelf-sync download
  ```

- Verify changes:

  ```sh
  uv run pytest
  uv run ruff check .
  uv run ty check
  ```

## Configuration

Settings are read by `audiobookshelf_sync/config.py` using the
`AUDIOBOOKSHELF_` environment prefix.

Source Audiobookshelf settings:

- `AUDIOBOOKSHELF_URL`
- `AUDIOBOOKSHELF_TOKEN`, or `AUDIOBOOKSHELF_USERNAME` and `AUDIOBOOKSHELF_PASSWORD`
- `AUDIOBOOKSHELF_DOWNLOAD_DIR`, defaulting to `./downloads`

## Code Map

- `audiobookshelf_sync/__main__.py`: Click commands and top-level async command wiring.
- `audiobookshelf_sync/api.py`: Audiobookshelf client creation and search result mapping.
- `audiobookshelf_sync/queue.py`: `audiobookshelf-sync.json` models and queue state helpers.
- `audiobookshelf_sync/tui.py`: Textual search and queue management UI.
- `audiobookshelf_sync/download.py`: Download queue processing and track file writes.
- `tests/`: Behavior tests for each module.

## Behavior Notes

- The queue file is `audiobookshelf-sync.json` in the current working directory.
- Search results are book rows only. Author matches are expanded to the author's books.
- In the TUI, queued search results show `[x]`; unqueued results show `[ ]`.
- In the TUI queue pane, `d` or Delete removes the highlighted queue item, and `r` resets it to `pending`.
- The downloader skips queue items marked `done`.
- The downloader skips track files that already exist at their final path.

## Testing Expectations

- Add or update tests with behavior changes.
- Prefer focused tests in the matching `tests/test_*.py` file.
- For Textual behavior, use `app.run_test()` as in `tests/test_tui.py`.
- For network-facing code, use fake sessions/responses instead of real Audiobookshelf servers.
- Before claiming completion, run:

  ```sh
  uv run pytest
  uv run ruff check .
  uv run ty check
  ```
