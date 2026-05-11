# audiobookshelf-sync

Search an Audiobookshelf server, queue audiobook downloads, and download queued
books to a local directory.

## Configuration

Set these environment variables before running commands:

```sh
export AUDIOBOOKSHELF_URL="https://audiobookshelf.example"
export AUDIOBOOKSHELF_DOWNLOAD_DIR="./downloads"
```

Set authentication with one of these:

```sh
export AUDIOBOOKSHELF_TOKEN="your-api-token"
```

or:

```sh
export AUDIOBOOKSHELF_USERNAME="your-username"
export AUDIOBOOKSHELF_PASSWORD="your-secret-password"
```

`AUDIOBOOKSHELF_DOWNLOAD_DIR` is optional and defaults to `./downloads`.

## Search and Queue

Open the interactive search TUI:

```sh
uv run audiobookshelf-sync search
```

Type a search query and press Enter. Select a result, then press `a` to add it
to the queue. The queue is stored in `audiobookshelf-sync.json` in the current
directory.

## Download

Process all pending queued books:

```sh
uv run audiobookshelf-sync download
```

Downloaded books are written under `AUDIOBOOKSHELF_DOWNLOAD_DIR`, with one
folder per book. Completed queue items are marked `done` in
`audiobookshelf-sync.json`.
