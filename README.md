# Tadabbur Pipeline

Local-first, open-source media ingestion and cataloguing pipeline for Tadabbur
(Islamic audio) content.

## What it does

1. Monitors configured YouTube channels.
2. Detects newly published videos.
3. Identifies likely Tadabbur/Tafsir content (deterministic rules first).
4. Downloads only approved media via `yt-dlp`.
5. Extracts M4A audio via FFmpeg.
6. Preserves source metadata and catalogues everything in SQLite.
7. Validates output, then makes it ready for publication.
8. Exports structured JSON for a future web application.

## Architecture

See `architect.md` for the full architecture and `todoagent.md` for the
implementation plan. Key principles:

- **Deterministic first, AI second** — rules classify content; a local Qwen
  model is an optional fallback only for ambiguous cases.
- **SQLite is the source of truth** — every state transition is persisted and
  resumable after crashes or reboots.
- **yt-dlp is isolated** behind `YtDlpClient` (`src/tadabbur/downloader/`).
- **Bounded retries + backoff + circuit breaker**, never anti-bot evasion.
- **Publishers are pluggable** — the core pipeline never depends on a
  publisher (Internet Archive / filesystem currently).

```
YouTube ─▶ yt-dlp ─▶ DISCOVER ─▶ RULE CLASSIFIER ─▶ QUEUE ─▶ DOWNLOAD
   ─▶ AUDIO (ffmpeg/m4a) ─▶ METADATA ─▶ TAG ─▶ VALIDATE ─▶ READY_TO_PUBLISH
   ─▶ Publisher (IA / filesystem) ─▶ Web JSON export
```

## Requirements

- Python 3.11+
- `yt-dlp`
- `ffmpeg`
- SQLite (built into Python)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configure

Copy `config/config.yaml` to your own file (or edit in place) and enable sources:

```yaml
sources:
  - id: ustaz_example
    name: "Ustaz Example"
    channel_url: "https://www.youtube.com/@ustaz-example"
    enabled: true
    language: ms
    rules:
      include: [tadabbur, tafsir, quran]
      exclude: [shorts, promo]
    rights_status: unknown      # unknown | open_license | permission_obtained | source_permitted | restricted | do_not_publish
    publication_policy: false   # false = never publish (archive only)
```

Set `--config /path/to/config.yaml` (or `TADABBUR_CONFIG`) so relative
`storage.base_dir` paths resolve next to your config.

Environment variables override config: `TADABBUR_LOG_LEVEL`, `TADABBUR_PROXY_URL`,
`TADABBUR_PROXY_ENABLED`, `TADABBUR_BASE_DIR`, `TADABBUR_SCHEDULER_DRY_RUN`
(see `src/tadabbur/config/loader.py`).

## Usage

```bash
tadabbur discover            # discover new media metadata
tadabbur classify            # classify discovered media (rules-first)
tadabbur download            # download queued media + extract audio
tadabbur process --video VIDEO_ID   # one video end-to-end
tadabbur validate            # gate media before publication
tadabbur publish --publisher filesystem   # or internet_archive (default)
tadabbur export              # write web/data JSON files
tadabbur worker --once       # run a single worker pass
tadabbur status              # pipeline summary
tadabbur failed              # list failed items
tadabbur retry --failed      # re-queue failed items
tadabbur inspect VIDEO_ID    # full record
```

### Pipeline states

```
DISCOVERED ─▶ CLASSIFIED ─▶ QUEUED ─▶ DOWNLOADING ─▶ DOWNLOADED
  ─▶ AUDIO_PROCESSING ─▶ PROCESSED ─▶ TAGGED ─▶ VALIDATED
  ─▶ READY_TO_PUBLISH ─▶ PUBLISHED
  └ (rejected) REJECTED   (uncertain) MANUAL_REVIEW   ─▶ FAILED (retryable)
```

### Storage layout

```
data/
├── database/tadabbur.sqlite
├── media/<speaker>/<year>/<month>/<source-id>/<VIDEO_ID>/
│   ├── audio.m4a  source.mp4  metadata.json  thumbnail.jpg
└── exports/lectures.json  speakers.json  surahs.json  categories.json  tags.json
```

## Tests

```bash
python -m pytest
```

All tests use mocked yt-dlp subprocesses (no YouTube access required); FFmpeg
tests generate synthetic audio locally.

## systemd (optional)

See `systemd/` for discovery + worker services and timers. Adjust paths to your
install, then:

```bash
sudo systemctl link $PWD/systemd/tadabbur-discovery.service
sudo systemctl link $PWD/systemd/tadabbur-worker.service
```

## License

MIT
