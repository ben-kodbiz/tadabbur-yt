# Tadabbur Audio Pipeline — Agent Implementation Plan

## 0. Project Objective

Build a modular, local-first, open-source Tadabbur media ingestion pipeline centered around `yt-dlp`.

The system shall:

1. Monitor configured YouTube channels.
2. Detect newly published videos.
3. Identify likely Tadabbur/Tafsir content.
4. Download only approved/relevant media.
5. Extract audio where appropriate.
6. Preserve source metadata.
7. Categorize and tag the audio deterministically.
8. Optionally use a small local Qwen model only for ambiguous classification/tagging.
9. Store everything in SQLite.
10. Resume safely after interruption or failure.
11. Publish approved content to Internet Archive through a pluggable publisher.
12. Provide structured data for a future Tadabbur web application.
13. Remain completely usable without paid APIs or cloud AI services.

The first implementation must focus ONLY on:

> YouTube → Tadabbur detection → audio → metadata → SQLite → archive-ready library.

Do not implement advanced RAG, embeddings, vector databases, autonomous agents, or complex orchestration in the initial stages.

---

# 1. Non-Negotiable Requirements

## 1.1 Open Source / Local First

All core functionality must work without:

* Google APIs
* OpenAI APIs
* paid AI APIs
* commercial cloud services
* proprietary SaaS dependencies

Preferred technologies:

* Python
* yt-dlp
* FFmpeg
* SQLite
* systemd
* local Qwen
* Whisper/whisper.cpp later
* FastAPI later
* plain HTML/CSS/JavaScript later

---

## 1.2 yt-dlp Is the Core Ingestion Engine

Do not replace yt-dlp with another downloader.

yt-dlp is responsible for:

* channel/video metadata discovery
* video identification
* downloading
* audio extraction
* subtitles where available
* thumbnails
* source metadata
* download resume capabilities
* format selection
* output naming

Keep yt-dlp isolated behind a Python service/module so that the rest of the application does not depend directly on subprocess implementation details.

Suggested interface:

```python
class YtDlpClient:
    def discover(...)
    def inspect(...)
    def download(...)
    def download_audio(...)
    def download_metadata(...)
```

---

# 2. Important Safety / Operational Boundary

The pipeline MUST NOT implement mechanisms intended to bypass YouTube anti-bot or access controls.

Do NOT implement:

* CAPTCHA solving
* browser fingerprint spoofing
* automated challenge bypass
* stealth browser automation
* proxy rotation specifically to evade enforcement
* fake human interaction
* deliberate anti-detection fingerprint manipulation
* automated account/session abuse

The system MAY implement legitimate operational resilience:

* user-configured proxy
* proxy health checking
* bounded retries
* exponential backoff
* randomized delay/jitter for load management
* configurable request rate limits
* cooldown after repeated failures
* graceful shutdown
* resume after interruption
* failure queues
* circuit breaker behavior
* manual retry
* persistent job state

The goal is:

> behave conservatively and recover reliably, not evade platform controls.

---

# 3. Stage 0 — Repository Foundation

## Tasks

* [ ] Create repository structure.
* [ ] Create Python package.
* [ ] Create `pyproject.toml`.
* [ ] Create `.gitignore`.
* [ ] Create configuration directory.
* [ ] Create test directory.
* [ ] Create documentation directory if necessary.
* [ ] Add logging infrastructure.
* [ ] Add CLI entry point.
* [ ] Add configuration loader.
* [ ] Add environment variable support.
* [ ] Add basic unit tests.

Suggested structure:

```text
tadabbur-pipeline/
├── README.md
├── ARCHITECTURE.md
├── TODOAGENT.md
├── LICENSE
├── pyproject.toml
├── config/
├── data/
├── logs/
├── src/
│   └── tadabbur/
├── tests/
└── systemd/
```

## Completion Criteria

```bash
python -m tadabbur --help
```

works.

Configuration loads successfully.

Logging works.

Tests pass.

---

# 4. Stage 1 — Configuration System

Create configuration for sources.

Example conceptual configuration:

```yaml
sources:
  - id: ustaz_example
    name: "Ustaz Example"
    platform: youtube
    channel_url: "..."
    enabled: true

    rules:
      include:
        - tadabbur
        - tafsir
        - quran

      exclude:
        - shorts
        - promo
```

Create separate configuration for:

```text
download
proxy
classification
storage
archive
scheduler
```

Never hard-code channel URLs or personal paths.

---

# 5. Stage 2 — SQLite Database

Create database schema.

Minimum tables:

```text
sources
media
media_files
classifications
tags
media_tags
processing_jobs
download_attempts
publish_jobs
```

Important fields:

```text
media.id
media.source_id
media.external_id
media.url
media.title
media.description
media.published_at
media.duration
media.status
media.created_at
media.updated_at
```

Use the YouTube video ID as the external immutable identifier.

Enforce uniqueness:

```text
(source_id, external_id)
```

This prevents duplicate downloads.

---

# 6. Stage 3 — Discovery Engine

Implement metadata-only discovery before downloading media.

The engine should:

1. Read configured channels.
2. Query yt-dlp for available metadata.
3. Extract:

   * video ID
   * title
   * URL
   * uploader
   * upload date
   * duration
   * description
   * thumbnail
4. Compare against SQLite.
5. Insert unseen videos.
6. Mark them as `DISCOVERED`.

Do NOT download media during this stage.

---

# 7. Stage 4 — Deterministic Tadabbur Classifier

Do NOT use an LLM yet.

Create a deterministic classifier.

Input:

```text
title
description
channel
```

Output:

```text
category
confidence
matched_rules
```

Example:

```text
"Tadabbur Surah Al-Kahfi Ayat 1-10"

category = tadabbur
confidence = 1.0
```

Use:

* case-insensitive matching
* normalized Unicode
* configurable keyword lists
* regex
* exclusion rules
* source-specific rules

Never rely exclusively on filename matching.

---

# 8. Stage 5 — Quran / Surah Metadata Extraction

Create a built-in Quran Surah dictionary.

Extract:

```text
surah
ayah_start
ayah_end
```

from titles/descriptions.

Use deterministic parsing first.

Examples:

```text
Surah Al-Kahfi Ayat 1-10

Surah Al-Mulk 1-5

Tadabbur Al-Baqarah 255

Al Kahfi ayat 10-15
```

Do not invent missing information.

If uncertain:

```text
null
```

is preferable to guessing.

---

# 9. Stage 6 — Download Queue

Introduce explicit processing states.

Recommended states:

```text
DISCOVERED
CLASSIFIED
REJECTED
QUEUED
DOWNLOADING
DOWNLOADED
AUDIO_PROCESSING
PROCESSED
TAGGED
VALIDATED
READY_TO_PUBLISH
PUBLISHED
FAILED
```

Every transition must be persisted in SQLite.

Never depend on in-memory state.

---

# 10. Stage 7 — yt-dlp Download Manager

Create:

```text
downloader/
├── client.py
├── options.py
├── parser.py
├── retry.py
└── validator.py
```

Requirements:

* invoke yt-dlp safely
* capture stdout/stderr
* record exit code
* record yt-dlp version
* record start/end time
* record attempts
* detect incomplete files
* validate final files
* support resume
* support configurable proxy
* support configurable download format
* never overwrite a valid completed file unnecessarily

Use yt-dlp's native resume behavior where appropriate.

---

# 11. Proxy Support

Support optional user-configured proxy.

Configuration example:

```yaml
proxy:
  enabled: false
  url: ""
  health_check: true
```

The proxy must be passed explicitly to yt-dlp.

Requirements:

* proxy is optional
* no proxy rotation by default
* validate proxy configuration
* log whether proxy is enabled without exposing credentials
* detect repeated proxy failures
* stop using an unhealthy proxy
* require manual/configured recovery

Do not build proxy rotation for bypassing platform restrictions.

---

# 12. Retry / Backoff / Cooldown

Implement resilient failure handling.

Recommended conceptual policy:

```text
Attempt 1
    ↓
short backoff
    ↓
Attempt 2
    ↓
longer backoff
    ↓
Attempt 3
    ↓
cooldown
    ↓
Attempt N
    ↓
FAILED
```

Use:

* exponential backoff
* bounded maximum delay
* jitter
* configurable maximum attempts

Example:

```text
base_delay = 10 seconds
max_delay = 10 minutes
max_attempts = 5
```

Do not retry indefinitely.

---

# 13. Circuit Breaker

If repeated platform/network failures occur:

```text
NORMAL
   |
   | repeated failures
   v
COOLDOWN
   |
   | cooldown expires
   v
HALF_OPEN
   |
   +---- success ----> NORMAL
   |
   +---- failure ----> COOLDOWN
```

This prevents the application from hammering a failing service.

---

# 14. Graceful Shutdown

The pipeline must handle:

```text
SIGINT
SIGTERM
```

without corrupting state.

On shutdown:

1. Stop creating new jobs.
2. Allow safe current operation to finish where possible.
3. Persist state.
4. Mark interrupted work as resumable.
5. Exit cleanly.

After restart:

```text
resume pending jobs
```

---

# 15. Stage 8 — Audio Extraction

Use FFmpeg through a controlled Python wrapper.

Pipeline:

```text
Downloaded video
      |
      v
FFmpeg
      |
      v
M4A audio
```

Recommended canonical listening format:

```text
M4A / AAC
```

Keep original media when configured.

Do not repeatedly transcode already processed files.

---

# 16. Stage 9 — Metadata Preservation

Every media item should have an archival directory:

```text
data/media/
└── ustaz-example/
    └── 2026/
        └── 08/
            └── VIDEO_ID/
                ├── audio.m4a
                ├── source.mp4
                ├── metadata.json
                ├── thumbnail.jpg
                ├── subtitles.vtt
                └── transcript.txt
```

Not every file is mandatory.

`metadata.json` should preserve source information.

---

# 17. Stage 10 — Deterministic Tagging

Before using an LLM, generate tags using rules.

Examples:

```text
quran
tadabbur
surah-al-kahfi
ayah-1-10
ustaz-example
bahasa-melayu
```

Controlled vocabulary is mandatory.

Do not let arbitrary model-generated tags pollute the database.

---

# 18. Stage 11 — Optional Qwen Classifier

Only implement after the deterministic pipeline works.

Qwen is a fallback for ambiguous content.

Recommended initial model class:

```text
Qwen 2B–3B instruct model
```

Do not require a large model.

Input:

```text
title
description
known metadata
```

Potential output:

```json
{
  "category": "tadabbur",
  "confidence": 0.91,
  "tags": [
    "quran",
    "sabar"
  ]
}
```

Constrain output to known categories/tags.

If confidence is below the configured threshold:

```text
MANUAL_REVIEW
```

Do not automatically publish uncertain results.

---

# 19. Important LLM Rule

The LLM must NEVER overwrite authoritative source metadata.

For example:

```text
YouTube title
channel
video ID
upload date
duration
```

come from yt-dlp.

The LLM can provide:

```text
classification
topics
optional tags
summary
```

It must not fabricate source information.

---

# 20. Stage 12 — Validation

Before a media item becomes publishable:

Check:

* [ ] source ID exists
* [ ] title exists
* [ ] media file exists
* [ ] audio file exists
* [ ] audio can be decoded
* [ ] file size > minimum threshold
* [ ] duration is sensible
* [ ] metadata exists
* [ ] classification exists
* [ ] rights status is known/allowed for intended publication
* [ ] no duplicate exists

Only then:

```text
READY_TO_PUBLISH
```

---

# 21. Stage 13 — Rights / Publication Policy

Never assume that an Islamic lecture is automatically free to redistribute.

Store:

```text
rights_status
publication_policy
```

Possible values:

```text
unknown
permission_obtained
open_license
source_permitted
restricted
do_not_publish
```

Publishing must stop if policy does not permit it.

The system should still be able to retain metadata/source references when redistribution is not permitted.

---

# 22. Stage 14 — Internet Archive Publisher

Implement publisher as a plugin/interface.

```python
class Publisher:
    def publish(self, media):
        ...
```

Implement:

```text
publishers/
└── internet_archive/
```

Requirements:

* resumable publishing
* persistent publish state
* retry
* validation
* logging
* no effect on core pipeline if IA is unavailable

If publishing fails:

```text
PUBLISH_PENDING
```

not:

```text
PIPELINE_FAILED
```

---

# 23. Stage 15 — Web Data Export

Before building a complicated API, generate simple JSON.

Example:

```text
web/data/
├── lectures.json
├── speakers.json
├── surahs.json
├── categories.json
└── tags.json
```

Pipeline:

```text
SQLite
   |
   v
JSON exporter
   |
   v
Web application
```

The web frontend must not directly manipulate the ingestion database.

---

# 24. Stage 16 — Tadabbur Web Application

Build after the pipeline is reliable.

Initial features:

* [ ] lecture listing
* [ ] audio player
* [ ] search
* [ ] speaker filtering
* [ ] Surah filtering
* [ ] category filtering
* [ ] tag filtering
* [ ] date filtering
* [ ] source link
* [ ] archive link
* [ ] responsive mobile UI

Keep frontend simple:

```text
HTML
CSS
JavaScript
```

No unnecessary framework unless later justified.

---

# 25. Stage 17 — Full-Text Search

Initially use:

```text
SQLite FTS5
```

Search:

```text
title
description
speaker
surah
tags
transcript
```

Do not introduce a vector database until there is a real requirement.

---

# 26. Stage 18 — Transcription

Future feature.

Use local:

```text
Whisper
or
whisper.cpp
```

Pipeline:

```text
audio
  |
  v
Whisper
  |
  v
transcript
  |
  +----> FTS5
  |
  +----> Qwen
  |
  +----> chapters
  |
  +----> improved tagging
```

Only introduce this after the basic audio pipeline is stable.

---

# 27. Stage 19 — Semantic Qwen Tagging

After transcripts exist, Qwen can become much more useful.

Potential tasks:

```text
topic classification
theme extraction
summary
chapter detection
Quran references
subject tagging
```

Still constrain the output to the project's controlled vocabulary.

---

# 28. Stage 20 — systemd Automation

Create:

```text
systemd/
├── tadabbur-discovery.service
├── tadabbur-discovery.timer
├── tadabbur-worker.service
└── tadabbur-worker.timer
```

The daily process should:

```text
discover
  ↓
classify
  ↓
queue
  ↓
download
  ↓
process
  ↓
validate
  ↓
publish
```

Every stage must be restartable.

---

# 29. CLI Requirements

Provide:

```bash
tadabbur discover
tadabbur classify
tadabbur download
tadabbur process
tadabbur validate
tadabbur publish
tadabbur worker
tadabbur status
tadabbur retry
tadabbur failed
tadabbur inspect VIDEO_ID
```

Also support:

```bash
tadabbur worker --dry-run
tadabbur discover --source ustaz-example
tadabbur retry --failed
```

---

# 30. Observability

Logs must clearly show:

```text
[DISCOVER]
[CLASSIFY]
[DOWNLOAD]
[AUDIO]
[TAG]
[VALIDATE]
[PUBLISH]
[ERROR]
```

Example:

```text
[DOWNLOAD] VIDEO_ID
[DOWNLOAD] attempt=1
[DOWNLOAD] proxy=enabled
[DOWNLOAD] status=success
[AUDIO] ffmpeg success
[TAG] category=tadabbur
[VALIDATE] success
[PUBLISH] queued
```

Never log secrets.

---

# 31. Testing Requirements

Every stage must have tests.

Minimum:

* [ ] configuration tests
* [ ] database tests
* [ ] duplicate detection
* [ ] keyword classification
* [ ] Surah extraction
* [ ] ayah extraction
* [ ] retry logic
* [ ] state transitions
* [ ] interrupted job recovery
* [ ] invalid media detection
* [ ] publisher failure handling

Use mocked yt-dlp subprocess calls for most tests.

Do not require YouTube access for unit tests.

---

# 32. Development Rule

Do NOT implement all stages in one pass.

After every stage:

1. Run tests.
2. Run a local smoke test.
3. Update documentation.
4. Commit changes.
5. Only then proceed.

Recommended Git milestones:

```text
stage-00-foundation
stage-01-config
stage-02-database
stage-03-discovery
stage-04-classifier
stage-05-download
stage-06-audio
stage-07-metadata
stage-08-validation
stage-09-archive
stage-10-web
stage-11-qwen
stage-12-transcription
```

---

# 33. Definition of v1

v1 is complete when:

```text
Configured YouTube channels
        |
        v
Daily discovery
        |
        v
Tadabbur filtering
        |
        v
Download
        |
        v
Audio extraction
        |
        v
Metadata
        |
        v
SQLite
        |
        v
Validation
        |
        v
Internet Archive queue
        |
        v
Web JSON
```

works unattended and survives:

* network failure
* process interruption
* machine reboot
* duplicate discovery
* failed downloads
* failed conversions
* failed publication

---

# 34. Do Not Build Yet

Explicitly postpone:

* vector database
* RAG
* autonomous agents
* multi-agent architecture
* Kubernetes
* Redis
* Celery
* Airflow
* n8n
* cloud AI
* browser automation
* anti-bot bypass
* proxy rotation
* recommendation engine
* semantic search
* mobile application

Build the boring reliable pipeline first.

The objective is:

> **Reliable ingestion before intelligence.**
