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
    rules:
      include: [tadabbur, tafsir, quran]
      exclude: [shorts, promo]
```

Environment variables override config: `TADABBUR_LOG_LEVEL`, `TADABBUR_PROXY_URL`,
`TADABBUR_BASE_DIR`, and more (see `src/tadabbur/config/loader.py`).

## Usage

```bash
tadabbur discover        # discover new media metadata
tadabbur classify        # classify discovered media
tadabbur download        # download queued media
tadabbur process --video VIDEO_ID
tadabbur validate
tadabbur publish
tadabbur worker --once   # run a single worker pass
tadabbur status
tadabbur failed
tadabbur retry --failed
tadabbur inspect VIDEO_ID
```

## Tests

```bash
python -m pytest
```

## License

MIT
