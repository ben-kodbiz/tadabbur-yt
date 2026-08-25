# Uploading Pipeline for Archived Third-Party Audio to YouTube

## 1. Purpose

This document defines an automated pipeline for organizing, validating, converting, tracking, and uploading audio content collected from permitted source channels into a central YouTube archive/channel.

The project is an **archive and discovery system**, not a content-ownership system.

Primary goals:

* Collect audio from configured source channels.
* Preserve source attribution and provenance.
* Avoid claiming ownership of third-party material.
* Organize hundreds or thousands of files.
* Convert audio into a YouTube-compatible upload format.
* Keep file sizes reasonably small without making speech difficult to understand.
* Generate a static visual/video container for audio-only material.
* Track every item in a database.
* Know exactly what is:

  * discovered
  * downloaded
  * processed
  * ready for upload
  * uploaded
  * failed
  * skipped
  * blocked for manual review
* Prevent accidental duplicate uploads.
* Support retries and resume after interruption.
* Preserve the original source URL and metadata.
* Require explicit review where copyright or reuse permission is uncertain.

---

# 2. Important Policy Boundary

A disclaimer or attribution **does not by itself grant permission to re-upload copyrighted material**.

The pipeline must therefore not treat:

> "I do not own this content"

as permission to upload.

The system should support different rights statuses and require the operator to classify content before publication.

Allowed database values:

```text
rights_status:

unknown
permission_confirmed
license_confirmed
public_domain
creative_commons
owned_by_operator
upload_not_authorized
manual_review_required
```

Only items with an explicitly approved publishing status should enter the automatic YouTube upload queue.

Recommended automatic-upload statuses:

```text
permission_confirmed
license_confirmed
public_domain
creative_commons
owned_by_operator
```

Everything else must remain:

```text
manual_review_required
```

or:

```text
upload_not_authorized
```

The pipeline must never automatically assume that attribution equals permission.

---

# 3. High-Level Architecture

```text
                    ┌─────────────────────┐
                    │  CONFIGURED SOURCES │
                    │ YouTube Channels    │
                    │ Playlists           │
                    │ Individual URLs     │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    DISCOVERY JOB    │
                    │ yt-dlp metadata     │
                    │ no duplicate fetch  │
                    └──────────┬──────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │       SQLite DB         │
                  │ source records          │
                  │ processing state        │
                  │ rights status           │
                  │ upload status           │
                  └────────────┬────────────┘
                               │
                  ┌────────────▼────────────┐
                  │   RIGHTS / REVIEW GATE  │
                  │                         │
                  │ Is upload authorized?   │
                  └───────┬─────────┬───────┘
                          │         │
                        YES         NO
                          │         │
                          ▼         ▼
                ┌──────────────┐  manual review
                │   DOWNLOAD   │  or archive only
                └──────┬───────┘
                       │
                       ▼
              ┌───────────────────┐
              │ ORIGINAL ARCHIVE  │
              │ optional preserve │
              └─────────┬─────────┘
                        │
                        ▼
              ┌───────────────────┐
              │ AUDIO PROCESSING  │
              │ normalize audio   │
              │ compress speech   │
              │ validate output   │
              └─────────┬─────────┘
                        │
                        ▼
              ┌───────────────────┐
              │ VIDEO GENERATION  │
              │ image + waveform  │
              │ attribution card  │
              │ MP4 for YouTube   │
              └─────────┬─────────┘
                        │
                        ▼
              ┌───────────────────┐
              │ QUALITY VALIDATOR │
              │ duration          │
              │ metadata          │
              │ file integrity    │
              │ duplicate check   │
              └─────────┬─────────┘
                        │
                        ▼
              ┌───────────────────┐
              │   UPLOAD QUEUE    │
              │ pending uploads   │
              └─────────┬─────────┘
                        │
                        ▼
              ┌───────────────────┐
              │ MANUAL/AUTHORIZED │
              │ YOUTUBE UPLOADER  │
              └─────────┬─────────┘
                        │
                 ┌──────┴───────┐
                 │              │
                 ▼              ▼
             SUCCESS          FAILURE
                 │              │
                 ▼              ▼
          record YouTube ID   retry queue
          mark uploaded       + error log
```

---

# 4. Recommended Project Structure

```text
uploading-pipeline/
│
├── README.md
├── pyproject.toml
├── requirements.txt
│
├── config/
│   ├── config.yaml
│   ├── sources.yaml
│   ├── channels.yaml
│   └── attribution_templates.yaml
│
├── data/
│   ├── pipeline.db
│   └── exports/
│
├── incoming/
│   ├── originals/
│   ├── audio/
│   └── metadata/
│
├── workspace/
│   ├── processing/
│   ├── rendered/
│   └── temp/
│
├── archive/
│   ├── originals/
│   ├── processed_audio/
│   └── uploaded/
│
├── assets/
│   ├── backgrounds/
│   ├── logos/
│   ├── attribution_cards/
│   └── fonts/
│
├── logs/
│   ├── pipeline.log
│   ├── uploads.log
│   └── errors.log
│
├── reports/
│
├── src/
│   ├── cli.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   │
│   ├── discovery/
│   │   ├── scanner.py
│   │   └── yt_metadata.py
│   │
│   ├── download/
│   │   └── downloader.py
│   │
│   ├── processing/
│   │   ├── audio.py
│   │   ├── normalize.py
│   │   ├── compress.py
│   │   └── validator.py
│   │
│   ├── render/
│   │   ├── background.py
│   │   ├── waveform.py
│   │   ├── attribution.py
│   │   └── video.py
│   │
│   ├── metadata/
│   │   ├── builder.py
│   │   ├── attribution.py
│   │   └── description.py
│   │
│   ├── rights/
│   │   ├── policy.py
│   │   └── gate.py
│   │
│   ├── upload/
│   │   ├── queue.py
│   │   └── youtube.py
│   │
│   └── reports/
│       └── generator.py
│
└── scripts/
    ├── run-discovery.sh
    ├── process-pending.sh
    ├── upload-approved.sh
    └── daily-report.sh
```

---

# 5. Pipeline Stages

## Stage 1 — Source Registration

The system must never rely on random filenames as the primary identity.

Every source channel or source URL should be registered.

Example:

```yaml
sources:
  - id: maulana-asri
    name: "Maulana Asri Yusof"
    platform: youtube
    channel_url: "SOURCE_URL"
    default_rights_status: manual_review_required
    attribution_name: "Original source: Maulana Asri Yusof"
    enabled: true

  - id: source-channel-2
    name: "Source Channel 2"
    platform: youtube
    channel_url: "SOURCE_URL"
    default_rights_status: manual_review_required
    enabled: true
```

The source record should contain:

* source ID
* source name
* original channel URL
* original content URL
* original title
* uploader/channel name
* publication date
* duration
* original media ID
* rights status
* permission evidence reference
* attribution text

---

# 6. Stage 2 — Discovery

Discovery should first collect metadata without downloading everything again.

Use `yt-dlp` metadata extraction.

Conceptual flow:

```text
configured source
      │
      ▼
yt-dlp metadata extraction
      │
      ▼
extract platform video ID
      │
      ├── already in database?
      │
      ├── YES → skip
      │
      └── NO
             │
             ▼
       insert new record
```

The strongest source identity should be:

```text
platform + original_video_id
```

For example:

```text
youtube:dQwExample123
```

Do not identify content primarily by title because titles can change.

---

# 7. Stage 3 — Rights and Publishing Gate

Before processing an item for publication:

```python
if rights_status not in APPROVED_FOR_UPLOAD:
    do_not_enqueue_for_upload()
```

Recommended states:

```text
DISCOVERED
    │
    ▼
RIGHTS_REVIEW
    │
    ├── authorized ──────────────► DOWNLOAD
    │
    ├── archive_only ────────────► ARCHIVE ONLY
    │
    └── unknown ─────────────────► MANUAL REVIEW
```

The database should store evidence notes such as:

```text
permission_note
license_url
permission_date
permission_reference
reviewed_by
reviewed_at
```

---

# 8. Stage 4 — Download

Download only after the item passes the appropriate review gate.

The downloader must:

* support resume
* avoid re-downloading completed files
* use temporary `.part` files
* verify file existence
* verify duration
* save original metadata JSON
* calculate checksum
* retry transient failures
* use configurable network settings
* never silently mark a failed download as complete

Recommended files:

```text
incoming/originals/
    source_id/
        original_video_id/
            source.json
            original.ext
            checksum.sha256
```

Example:

```text
incoming/originals/
└── maulana-asri/
    └── abc123xyz/
        ├── source.json
        ├── original.webm
        └── checksum.sha256
```

---

# 9. Stage 5 — Audio Extraction and Compression

## Goal

Create speech-focused audio that is:

* clear enough for lectures
* small enough to save storage and bandwidth
* stable for long recordings
* suitable as input for YouTube video rendering

For speech, extremely high audio bitrates are usually wasteful.

Recommended profiles:

### Profile A — Compact Speech

```text
Codec: Opus
Bitrate: 32 kbps
Sample rate: 48 kHz
Channels: Mono
Use case: speech archive
```

### Profile B — Balanced Speech

```text
Codec: Opus
Bitrate: 48 kbps
Sample rate: 48 kHz
Channels: Mono
Use case: most lectures
```

### Profile C — Higher Quality

```text
Codec: Opus
Bitrate: 64 kbps
Sample rate: 48 kHz
Channels: Mono
Use case: lectures with better source quality
```

Default recommendation:

```text
48 kbps Opus mono
```

This should give a much smaller archive than keeping large source audio.

Example approximate size:

```text
1 hour at 48 kbps ≈ 22 MB
```

Actual size will vary.

### Important

Keep the compressed Opus file as the **archive audio derivative**.

Example:

```text
processed_audio.opus
```

Do not repeatedly transcode an already compressed derivative.

Always regenerate derivatives from the best available original source.

---

# 10. Audio Processing Rules

The processor should:

1. Inspect source media.
2. Extract the best available audio.
3. Convert to a temporary working format if needed.
4. Apply safe loudness normalization.
5. Remove obvious technical silence only if configured.
6. Encode the final archival derivative.
7. Validate duration against source.
8. Save processing metadata.

Processing flow:

```text
ORIGINAL
    │
    ▼
ffprobe inspection
    │
    ▼
audio extraction
    │
    ▼
normalization
    │
    ▼
Opus encoding
    │
    ▼
validation
    │
    ▼
archive processed audio
```

Validation must compare:

```text
source duration
processed duration
duration difference tolerance
audio stream exists
file size > minimum
codec matches expected profile
```

---

# 11. Stage 6 — Create a YouTube-Compatible Video

YouTube does not accept a plain MP3/Opus audio file as a normal video upload.

The pipeline should create an MP4 container.

Recommended approach:

```text
Compressed Audio
       +
Static Background / Simple Visual
       +
Attribution Overlay
       =
YouTube MP4
```

The visual should be simple and consistent.

Possible layouts:

### Layout 1 — Static Archive Card

```text
┌─────────────────────────────────────┐
│                                     │
│             CHANNEL LOGO            │
│                                     │
│           ORIGINAL TITLE            │
│                                     │
│        Original Speaker/Source      │
│                                     │
│     Archived / collected by XYZ     │
│                                     │
│  Original source link in description│
│                                     │
└─────────────────────────────────────┘
```

### Layout 2 — Slow Animated Background

```text
background image
      +
subtle motion
      +
title
      +
source attribution
      +
audio
```

### Layout 3 — Waveform

```text
background
   +
speaker/source
   +
waveform visualization
   +
current title
   +
audio
```

Avoid unnecessarily complex rendering.

For an archive channel, a static or lightly animated card is cheaper and faster to generate.

---

# 12. YouTube Output Profile

For the rendered video:

```text
Container: MP4
Video codec: H.264
Pixel format: yuv420p
Audio codec: AAC
Audio bitrate: 64–96 kbps
Resolution: 1280x720
Frame rate: 24 or 30 fps
```

Recommended default:

```text
1280x720
H.264 CRF-based encoding
AAC 64 kbps mono
24 fps
```

Because the visual is mostly static, the video bitrate can be relatively low.

The renderer should use sensible encoding settings rather than blindly assigning a huge fixed bitrate.

Important distinction:

```text
ARCHIVE AUDIO:
Opus 48 kbps mono

YOUTUBE VIDEO AUDIO:
AAC 64 kbps mono

YOUTUBE VIDEO:
H.264 optimized for mostly static imagery
```

This gives:

* small internal archive audio
* YouTube-compatible MP4
* reasonably small intermediate upload files

---

# 13. Optional Smart Video Rendering

The pipeline may detect content type.

Example:

```text
LECTURE
  → static title card

QUESTION & ANSWER
  → title card + section labels

SHORT TALK
  → waveform

LONG LECTURE
  → low-motion background
```

Initial implementation should remain simple.

Do not build a GPU-heavy visual production system unless there is a real benefit.

---

# 14. Metadata Generation

The metadata generator should preserve the original identity.

Suggested title format:

```text
[Archive] Original Title — Original Speaker
```

Or:

```text
Original Speaker | Original Title
```

Description template:

```text
ARCHIVE / ATTRIBUTION NOTICE

This recording originates from the original source listed below.

Original title:
{original_title}

Original speaker/channel:
{source_name}

Original source:
{source_url}

Original publication URL:
{original_url}

This channel acts as a central collection/archive and does not claim authorship of the original recording.

Rights status:
{rights_status}

{additional_permission_or_license_text}

If you are the rights holder and believe this upload should be changed or removed, please contact the channel operator.
```

Do not automatically generate false statements such as:

```text
Used with permission
```

unless permission has actually been recorded.

---

# 15. Database Design

Use SQLite.

Primary database:

```text
data/pipeline.db
```

## Table: sources

```sql
CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    source_key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    channel_url TEXT,
    attribution_text TEXT,
    default_rights_status TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
```

---

## Table: media_items

```sql
CREATE TABLE media_items (
    id INTEGER PRIMARY KEY,

    source_id INTEGER NOT NULL,

    platform TEXT NOT NULL,
    original_media_id TEXT NOT NULL,

    original_url TEXT NOT NULL,
    original_title TEXT,

    uploader_name TEXT,
    published_at TEXT,

    duration_seconds REAL,

    rights_status TEXT NOT NULL DEFAULT 'manual_review_required',
    rights_reviewed_at TEXT,
    rights_notes TEXT,
    permission_reference TEXT,

    discovery_status TEXT NOT NULL DEFAULT 'discovered',

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(platform, original_media_id),

    FOREIGN KEY(source_id) REFERENCES sources(id)
);
```

---

## Table: files

```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY,

    media_item_id INTEGER NOT NULL,

    file_type TEXT NOT NULL,

    path TEXT NOT NULL,

    extension TEXT,
    size_bytes INTEGER,

    sha256 TEXT,

    codec TEXT,
    bitrate INTEGER,
    duration_seconds REAL,

    created_at TEXT NOT NULL,

    FOREIGN KEY(media_item_id) REFERENCES media_items(id)
);
```

Possible `file_type` values:

```text
original_media
original_audio
processed_opus
youtube_mp4
thumbnail
metadata_json
```

---

## Table: processing_jobs

```sql
CREATE TABLE processing_jobs (
    id INTEGER PRIMARY KEY,

    media_item_id INTEGER NOT NULL,

    job_type TEXT NOT NULL,

    status TEXT NOT NULL,

    attempts INTEGER DEFAULT 0,

    started_at TEXT,
    completed_at TEXT,

    error_message TEXT,

    FOREIGN KEY(media_item_id) REFERENCES media_items(id)
);
```

Job types:

```text
discover
download
extract_audio
normalize
compress
render_video
validate
generate_metadata
upload
```

Statuses:

```text
pending
running
completed
failed
retry
skipped
blocked
```

---

## Table: uploads

```sql
CREATE TABLE uploads (
    id INTEGER PRIMARY KEY,

    media_item_id INTEGER NOT NULL,

    platform TEXT NOT NULL,

    upload_status TEXT NOT NULL,

    platform_video_id TEXT,
    platform_url TEXT,

    title_used TEXT,

    uploaded_at TEXT,

    attempt_count INTEGER DEFAULT 0,

    error_message TEXT,

    FOREIGN KEY(media_item_id) REFERENCES media_items(id)
);
```

Upload statuses:

```text
not_queued
pending_review
queued
uploading
uploaded
failed
retry
skipped
blocked
```

---

# 16. State Machine

Each media item should follow a controlled state machine.

```text
DISCOVERED
    │
    ▼
RIGHTS_REVIEW
    │
    ├── NOT AUTHORIZED ───────────────► BLOCKED
    │
    ├── ARCHIVE ONLY ─────────────────► ARCHIVED
    │
    └── AUTHORIZED
           │
           ▼
       DOWNLOAD_PENDING
           │
           ▼
       DOWNLOADING
           │
           ├── error ─────────────────► DOWNLOAD_RETRY
           │
           ▼
       DOWNLOADED
           │
           ▼
       AUDIO_PROCESSING
           │
           ▼
       AUDIO_READY
           │
           ▼
       VIDEO_RENDERING
           │
           ▼
       VALIDATION
           │
           ├── fail ──────────────────► PROCESSING_RETRY
           │
           ▼
       READY_FOR_UPLOAD
           │
           ▼
       UPLOAD_REVIEW
           │
           ▼
       UPLOAD_QUEUED
           │
           ▼
       UPLOADING
           │
           ├── fail ──────────────────► UPLOAD_RETRY
           │
           ▼
       UPLOADED
```

---

# 17. Duplicate Protection

The pipeline must have multiple duplicate checks.

## Level 1 — Platform ID

```text
youtube + original_video_id
```

This is the primary check.

## Level 2 — Original URL

Check whether the original URL already exists.

## Level 3 — File Checksum

Calculate SHA-256:

```text
sha256(original file)
sha256(processed audio)
sha256(rendered video)
```

## Level 4 — Title Similarity

Optional warning only.

Example:

```text
Similarity > configured threshold
```

This should flag an item for review, not automatically delete it.

---

# 18. Upload Queue

Never scan folders and upload everything blindly.

The database must control the queue.

Example command:

```bash
pipeline queue list
```

Output:

```text
ID     STATUS             TITLE
------------------------------------------------
101    READY_FOR_UPLOAD   Tafsir Surah Al-Fatihah
102    RIGHTS_REVIEW      Kuliah Maghrib
103    FAILED             Hadith Lecture
104    UPLOADED           Aqidah Class
105    BLOCKED             Permission unclear
```

Upload only approved items:

```bash
pipeline upload run --limit 5
```

Or a specific item:

```bash
pipeline upload item 101
```

Dry run:

```bash
pipeline upload run --dry-run
```

---

# 19. Retry System

Every external operation can fail.

Retryable operations:

* metadata discovery
* downloading
* audio conversion
* rendering
* validation
* upload

Recommended retry schedule:

```text
Attempt 1 → immediately
Attempt 2 → 5 minutes
Attempt 3 → 30 minutes
Attempt 4 → 2 hours
Attempt 5 → manual review
```

Store the exact error.

Never hide errors behind:

```text
something went wrong
```

Store:

```text
timestamp
job
command category
exception
return code
stderr summary
attempt number
```

---

# 20. Resume Support

The pipeline must survive:

* PC reboot
* network loss
* power interruption
* process crash
* storage problems
* upload failure

On startup:

```text
1. Find jobs marked RUNNING.
2. Check whether the process actually completed.
3. Validate output files.
4. If valid → mark completed.
5. If incomplete → mark retry.
6. Resume from the earliest unfinished stage.
```

Never restart the whole pipeline unnecessarily.

Example:

```text
Downloaded ✓
Audio extracted ✓
Audio compressed ✓
Video rendering ✓
Upload ✗

Next run:
→ upload only
```

---

# 21. File Naming

Never depend on the title as the unique filename.

Recommended:

```text
{source_key}__{original_media_id}__{safe_slug}
```

Example:

```text
maulana-asri__abc123xyz__tafsir-surah-al-fatihah
```

Files:

```text
maulana-asri__abc123xyz__original.webm
maulana-asri__abc123xyz__audio.opus
maulana-asri__abc123xyz__youtube.mp4
maulana-asri__abc123xyz__metadata.json
```

---

# 22. Processing Manifest

Each item should have a JSON manifest.

Example:

```json
{
  "media_id": "abc123xyz",
  "source_key": "maulana-asri",
  "original_url": "SOURCE_URL",
  "original_title": "Original Title",
  "rights_status": "permission_confirmed",
  "files": {
    "original": "original.webm",
    "archive_audio": "audio.opus",
    "youtube_video": "youtube.mp4"
  },
  "processing": {
    "audio_profile": "speech-balanced",
    "archive_codec": "opus",
    "archive_bitrate_kbps": 48,
    "youtube_audio_codec": "aac",
    "youtube_audio_bitrate_kbps": 64,
    "video_codec": "h264"
  }
}
```

---

# 23. Audio Profiles Configuration

```yaml
audio_profiles:

  speech_compact:
    codec: opus
    bitrate_kbps: 32
    channels: 1
    sample_rate: 48000

  speech_balanced:
    codec: opus
    bitrate_kbps: 48
    channels: 1
    sample_rate: 48000

  speech_high:
    codec: opus
    bitrate_kbps: 64
    channels: 1
    sample_rate: 48000
```

Default:

```yaml
default_audio_profile: speech_balanced
```

---

# 24. Rendering Profiles

```yaml
render_profiles:

  youtube_720p_static:
    width: 1280
    height: 720
    fps: 24
    video_codec: libx264
    audio_codec: aac
    audio_bitrate_kbps: 64
    visual_mode: static

  youtube_720p_waveform:
    width: 1280
    height: 720
    fps: 24
    video_codec: libx264
    audio_codec: aac
    audio_bitrate_kbps: 64
    visual_mode: waveform
```

---

# 25. Manual Review Dashboard

A lightweight local web dashboard is recommended.

Do not build a complicated cloud backend.

Suggested stack:

```text
Python
+
SQLite
+
FastAPI or Flask
+
Simple HTML
+
Minimal JavaScript
```

Dashboard pages:

```text
/overview

/sources

/media

/review

/queue

/uploads

/failures

/reports
```

Important actions:

```text
Approve rights
Block upload
Mark archive-only
Retry processing
Retry upload
Open original source
Open local file
View metadata
View error
Export CSV
```

---

# 26. Daily Pipeline

Recommended daily automation:

```text
┌───────────────────┐
│ 1. DISCOVER       │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 2. REGISTER DB    │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 3. RIGHTS GATE    │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 4. DOWNLOAD       │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 5. PROCESS AUDIO  │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 6. RENDER VIDEO   │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 7. VALIDATE       │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 8. QUEUE APPROVED │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 9. UPLOAD         │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ 10. VERIFY DB     │
└───────────────────┘
```

---

# 27. Suggested CLI

```bash
pipeline discover
```

Find new media.

```bash
pipeline status
```

Show pipeline summary.

```bash
pipeline review list
```

Show items requiring rights review.

```bash
pipeline review approve <id>
```

Mark rights status appropriately after operator review.

```bash
pipeline process pending
```

Process eligible downloaded items.

```bash
pipeline queue list
```

Show upload queue.

```bash
pipeline upload run --limit 3
```

Upload approved queued items.

```bash
pipeline retry failed
```

Retry failed jobs.

```bash
pipeline report daily
```

Generate a report.

---

# 28. Reports

Generate reports in:

```text
JSON
CSV
Markdown
```

Daily report example:

```text
DISCOVERED TODAY:        12
NEW ITEMS:               8
DUPLICATES SKIPPED:      4

RIGHTS REVIEW REQUIRED:  5
AUTHORIZED:              3
BLOCKED:                 0

DOWNLOADED:              3
AUDIO PROCESSED:         3
VIDEOS RENDERED:         3

READY FOR UPLOAD:        3
UPLOADED:                2
FAILED:                  1
```

---

# 29. Storage Management

The pipeline should support storage policies.

Example:

```yaml
storage:

  keep_originals: true

  keep_processed_audio: true

  keep_youtube_mp4_after_upload: true

  delete_temp_after_success: true

  verify_sha256: true
```

Recommended for a long-term archive:

```text
Original source       → keep if storage permits
Processed Opus        → keep
YouTube MP4           → optional but useful
Temporary files       → delete automatically
Metadata JSON         → always keep
Checksums             → always keep
```

---

# 30. Upload Verification

An upload is not complete merely because the upload command exits successfully.

After upload:

```text
1. Record returned platform video ID.
2. Record returned URL.
3. Confirm upload record exists.
4. Save upload timestamp.
5. Mark database item UPLOADED.
```

Never mark an item uploaded before the platform ID is recorded.

---

# 31. Failure Categories

Use structured failure categories:

```text
NETWORK_ERROR
AUTH_ERROR
SOURCE_UNAVAILABLE
DOWNLOAD_ERROR
FILE_CORRUPT
DISK_FULL
FFMPEG_ERROR
VALIDATION_ERROR
METADATA_ERROR
UPLOAD_ERROR
RIGHTS_BLOCKED
UNKNOWN_ERROR
```

This makes troubleshooting much easier when processing hundreds of files.

---

# 32. Concurrency

Initial safe defaults:

```yaml
workers:

  discovery: 1
  download: 1
  audio_processing: 1
  video_rendering: 1
  upload: 1
```

Do not start with parallel video rendering.

For a single-machine setup, stability is more valuable than maximum throughput.

Later, allow:

```text
download worker
+
audio worker
+
render worker
```

But each job must remain database-locked to prevent two workers processing the same media item.

---

# 33. Database Locking

Before processing:

```sql
UPDATE processing_jobs
SET status = 'running'
WHERE id = ?
AND status IN ('pending', 'retry');
```

The worker must verify it successfully claimed the job.

This prevents:

```text
Worker A ──► processing item 101
Worker B ──► processing item 101
```

at the same time.

---

# 34. Safety Against Accidental Mass Upload

The uploader must have limits.

Configuration:

```yaml
upload:

  enabled: false

  require_manual_enable: true

  max_uploads_per_run: 3

  max_uploads_per_day: 5

  dry_run_default: true
```

For production:

```text
First:
discover → process → validate

Then:
review queue

Then:
explicitly enable upload
```

Never let a cron job silently upload hundreds of items because of a database bug.

---

# 35. Recommended Implementation Order

## Phase 1 — Foundation

Build:

* [ ] Project structure
* [ ] Configuration loader
* [ ] SQLite database
* [ ] Database migrations
* [ ] Logging
* [ ] CLI
* [ ] Status reporting

## Phase 2 — Discovery

Build:

* [ ] Source configuration
* [ ] Metadata discovery
* [ ] Original media ID detection
* [ ] Duplicate detection
* [ ] Database registration

## Phase 3 — Rights Gate

Build:

* [ ] Rights status field
* [ ] Permission evidence fields
* [ ] Manual review queue
* [ ] Block unauthorized uploads
* [ ] Archive-only state

## Phase 4 — Download

Build:

* [ ] yt-dlp integration
* [ ] Resume support
* [ ] Metadata preservation
* [ ] Checksums
* [ ] Retry logic
* [ ] File validation

## Phase 5 — Audio Processing

Build:

* [ ] ffprobe inspection
* [ ] Audio extraction
* [ ] Loudness normalization
* [ ] Opus encoding
* [ ] Speech profiles
* [ ] Duration validation

## Phase 6 — Video Rendering

Build:

* [ ] Static background
* [ ] Attribution card
* [ ] Title overlay
* [ ] FFmpeg rendering
* [ ] MP4 validation

## Phase 7 — Metadata

Build:

* [ ] Title templates
* [ ] Attribution description
* [ ] Source links
* [ ] Permission/license text
* [ ] Metadata JSON

## Phase 8 — Upload Queue

Build:

* [ ] Database queue
* [ ] Pre-upload validation
* [ ] Manual approval
* [ ] Upload limits
* [ ] Dry-run mode

## Phase 9 — Upload Integration

Build:

* [ ] Authorized YouTube upload mechanism
* [ ] Upload response handling
* [ ] Video ID storage
* [ ] Retry handling
* [ ] Post-upload verification

## Phase 10 — Dashboard

Build:

* [ ] Overview
* [ ] Rights review
* [ ] Upload queue
* [ ] Failures
* [ ] Retry buttons
* [ ] CSV export

---

# 36. Final Design Principle

The pipeline must treat these as separate things:

```text
SOURCE ARCHIVE
≠
RIGHT TO PUBLISH
≠
AUDIO PROCESSING
≠
YOUTUBE UPLOAD
```

A file can exist in the archive database without being eligible for publication.

The core record flow should therefore be:

```text
DISCOVER
   │
   ▼
RECORD PROVENANCE
   │
   ▼
CHECK RIGHTS STATUS
   │
   ├── NOT APPROVED → ARCHIVE / REVIEW ONLY
   │
   └── APPROVED
          │
          ▼
       DOWNLOAD
          │
          ▼
       COMPRESS AUDIO
          │
          ▼
       RENDER SMALL MP4
          │
          ▼
       VALIDATE
          │
          ▼
       QUEUE
          │
          ▼
       EXPLICITLY APPROVED UPLOAD
          │
          ▼
       RECORD PLATFORM VIDEO ID
          │
          ▼
       MARK UPLOADED
```

The database is the source of truth.

Folders are storage.

Filenames are convenience.

The pipeline must always be able to answer:

```text
Where did this content come from?
What is its original URL?
Who is the original source?
What is the rights status?
Do we have permission or a qualifying license to publish it?
Has it been downloaded?
Has it been processed?
Where are the files?
Has it already been uploaded?
What is the platform video ID?
Did processing fail?
Can it safely resume?
```

If the system can answer those questions reliably, it can scale from 50 recordings to thousands without turning into a folder-management nightmare.
