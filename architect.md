# Tadabbur Audio Pipeline Architecture

## 1. Overview

The Tadabbur Audio Pipeline is a local-first, open-source media ingestion and cataloguing system.

Its primary purpose is to automatically discover relevant Islamic audio/video content from configured YouTube channels, identify Tadabbur material, download and process the media, catalogue it, and make approved content available to archival and web publishing systems.

The architecture deliberately separates:

```text
Discovery
Processing
Cataloguing
Storage
Publishing
Presentation
```

This allows the project to grow from a simple Tadabbur downloader into a broader Islamic media archive without rewriting the core.

---

# 2. High-Level Architecture

```text
                    CONFIGURED SOURCES
                           |
                           v
                 +--------------------+
                 |   DISCOVERY ENGINE |
                 |      yt-dlp        |
                 +---------+----------+
                           |
                           v
                 +--------------------+
                 |   SQLite DATABASE  |
                 |                    |
                 | discovered media   |
                 | processing state   |
                 +---------+----------+
                           |
                           v
                 +--------------------+
                 | CLASSIFICATION     |
                 |                    |
                 | Rules first        |
                 | Qwen fallback      |
                 +---------+----------+
                           |
                           v
                 +--------------------+
                 |   DOWNLOAD QUEUE   |
                 +---------+----------+
                           |
                           v
                 +--------------------+
                 |     yt-dlp         |
                 |                    |
                 | video/audio        |
                 | subtitles          |
                 | metadata           |
                 +---------+----------+
                           |
                           v
                 +--------------------+
                 |      FFmpeg        |
                 |                    |
                 | audio extraction   |
                 | normalization      |
                 +---------+----------+
                           |
                           v
                 +--------------------+
                 | METADATA / TAGGING |
                 +---------+----------+
                           |
                           v
                 +--------------------+
                 |     VALIDATOR      |
                 +---------+----------+
                           |
                    READY_TO_PUBLISH
                           |
             +-------------+-------------+
             |                           |
             v                           v
   +-------------------+       +-------------------+
   | Internet Archive  |       |   Web Publisher   |
   +-------------------+       +-------------------+
                                         |
                                         v
                              +---------------------+
                              | Tadabbur Web App    |
                              +---------------------+
```

---

# 3. Core Design Principle

The architecture follows:

> **Deterministic infrastructure first, AI second.**

Do not make an LLM responsible for basic media management.

The system should work perfectly without an LLM.

Qwen is an optional intelligence layer for cases where deterministic rules cannot confidently classify or tag content.

---

# 4. Major Components

```text
src/tadabbur/
│
├── config/
├── discovery/
├── downloader/
├── audio/
├── metadata/
├── classifier/
├── tagging/
├── database/
├── jobs/
├── validator/
├── publishers/
├── exporters/
├── scheduler/
└── cli/
```

---

# 5. Source Layer

Sources are configured externally.

Example:

```text
YouTube Channel A
YouTube Channel B
YouTube Channel C
```

Each source has:

```text
source_id
name
platform
channel_url
channel_id
enabled
classification rules
download policy
publication policy
```

The core pipeline must not contain hard-coded knowledge about individual ustaz.

---

# 6. Discovery Layer

The discovery layer uses yt-dlp.

Its job is NOT to download everything.

It first obtains metadata:

```text
video ID
title
description
channel
upload date
duration
URL
thumbnail
```

Then the discovery engine compares the result with SQLite.

```text
YouTube
   |
   v
yt-dlp metadata
   |
   v
Normalize
   |
   v
SQLite duplicate check
   |
   +---- already exists ----> ignore
   |
   +---- new ---------------> DISCOVERED
```

This makes daily discovery cheap.

---

# 7. yt-dlp Boundary

yt-dlp should be isolated behind an internal adapter.

```text
Application
     |
     v
YtDlpClient
     |
     v
yt-dlp subprocess
     |
     v
YouTube
```

The application should not scatter raw subprocess calls throughout the codebase.

This gives one location for:

* command construction
* version detection
* error parsing
* proxy configuration
* retry handling
* output parsing
* download validation

---

# 8. Network Resilience

The downloader supports optional proxy configuration.

```text
Application
     |
     v
Network Configuration
     |
     +---- direct
     |
     +---- configured proxy
     |
     v
yt-dlp
```

Proxy support exists for legitimate network routing and connectivity.

The architecture intentionally does NOT implement:

```text
proxy rotation for evasion
CAPTCHA bypass
fingerprint spoofing
browser stealth
challenge bypass
fake human activity
```

Instead the system uses:

```text
bounded retries
exponential backoff
jitter
rate limiting
cooldowns
circuit breakers
```

The desired behavior is conservative:

```text
failure
   |
   v
wait
   |
   v
retry
   |
   v
failure
   |
   v
longer cooldown
   |
   v
retry
   |
   v
persistent failure
   |
   v
STOP
```

This protects both the service and the local system from runaway retry loops.

---

# 9. Processing State Machine

The database is the source of truth.

```text
                  DISCOVERED
                       |
                       v
                  CLASSIFIED
                   /       \
              rejected     accepted
                 |             |
                 v             v
              REJECTED       QUEUED
                               |
                               v
                          DOWNLOADING
                           /       \
                      failed       success
                        |             |
                        v             v
                      FAILED       DOWNLOADED
                                      |
                                      v
                                AUDIO_PROCESSING
                                  /         \
                             failed         success
                               |              |
                               v              v
                             FAILED        PROCESSED
                                              |
                                              v
                                            TAGGED
                                              |
                                              v
                                          VALIDATED
                                              |
                                              v
                                      READY_TO_PUBLISH
                                              |
                                +-------------+-------------+
                                |                           |
                                v                           v
                           IA PUBLISHED                WEB PUBLISHED
```

Every state transition is persisted.

---

# 10. Failure Recovery

A failed operation must never destroy the entire pipeline.

For example:

```text
DOWNLOAD
   |
   X network failure
   |
   v
DOWNLOAD_FAILED
```

The next worker can resume it.

Likewise:

```text
FFMPEG
   |
   X process killed
   |
   v
AUDIO_PROCESSING
```

On restart the validator determines whether the output is valid.

If invalid:

```text
delete incomplete output
retry
```

If valid:

```text
continue
```

---

# 11. Database Architecture

SQLite is the initial database.

```text
                 SQLite
                    |
        +-----------+-----------+
        |           |           |
      media       jobs       taxonomy
        |           |
        |           +---- download attempts
        |           +---- processing attempts
        |           +---- publication attempts
        |
        +---- classifications
        +---- tags
        +---- files
```

SQLite is sufficient because the initial system is primarily a single-machine pipeline.

There is no reason to introduce PostgreSQL until real multi-user/concurrent requirements appear.

---

# 12. Media Identity

Every source item has:

```text
source_id
external_id
```

For YouTube:

```text
external_id = YouTube video ID
```

Unique constraint:

```text
(source_id, external_id)
```

This prevents duplicate downloads.

The local filename is NOT the identity.

---

# 13. Storage Architecture

Recommended:

```text
data/
├── database/
│   └── tadabbur.sqlite
│
├── media/
│   └── <speaker>/
│       └── <year>/
│           └── <month>/
│               └── <source-id>/
│                   ├── audio.m4a
│                   ├── source.mp4
│                   ├── metadata.json
│                   ├── thumbnail.jpg
│                   ├── subtitles.vtt
│                   └── transcript.txt
│
└── exports/
    ├── lectures.json
    ├── speakers.json
    └── taxonomy.json
```

Files are optional depending on processing configuration.

---

# 14. Classification Architecture

Classification has two layers.

```text
             MEDIA METADATA
                    |
                    v
          +-------------------+
          | RULE CLASSIFIER   |
          +---------+---------+
                    |
             confidence high?
               /          \
             yes            no
             |              |
             v              v
           ACCEPT        QWEN
                            |
                            v
                      classification
```

## Rule classifier

Uses:

* keywords
* regular expressions
* source configuration
* title
* description
* Surah dictionary

## Qwen classifier

Optional.

Use a small local Qwen model approximately in the 2B–3B range initially.

It should only handle ambiguous cases.

---

# 15. Why No LLM Initially?

A title such as:

```text
Tadabbur Surah Al-Kahfi Ayat 1-10
```

can be parsed deterministically.

The system can extract:

```text
category = tadabbur
surah = Al-Kahfi
ayah_start = 1
ayah_end = 10
```

An LLM would add complexity without improving this case.

Therefore:

> LLM is a fallback, not a dependency.

---

# 16. Controlled Taxonomy

Taxonomy must be centrally defined.

Initial categories:

```text
tadabbur
tafsir
quran
other
```

Initial focus:

```text
tadabbur
```

Future categories may include:

```text
hadith
sirah
aqidah
fiqh
akhlaq
khutbah
```

but they should not be implemented until required.

---

# 17. Tags

Tags use a controlled vocabulary.

Examples:

```text
quran
tadabbur
sabar
syukur
taqwa
iman
akhirat
doa
akhlak
keluarga
```

Tags may be generated through:

```text
rules
+
optional Qwen
```

but all tags must be validated against the taxonomy.

---

# 18. Qwen Boundary

Qwen must never become the authority for:

```text
source
video ID
channel
upload date
duration
original title
original URL
```

Those values come from yt-dlp/source metadata.

Qwen is allowed to suggest:

```text
category
topic
tags
summary
```

The database stores the model name/version used.

Example:

```text
classifier_model = qwen-3b
classifier_version = x.y
```

This allows future reclassification.

---

# 19. Audio Processing

The canonical listening format should initially be:

```text
M4A / AAC
```

Pipeline:

```text
source video
     |
     v
FFmpeg
     |
     v
canonical audio
```

Do not repeatedly transcode the same audio.

Every processing operation should be idempotent.

---

# 20. Idempotency

Running the same command twice must not create duplicate work.

Example:

```bash
tadabbur process VIDEO_ID
```

If the audio already exists and passes validation:

```text
already processed
```

The system should continue rather than regenerate it.

This is essential for unattended operation.

---

# 21. Publishers

Publishing is deliberately separated from ingestion.

```text
                    CORE MEDIA
                         |
              +----------+----------+
              |                     |
              v                     v
      Internet Archive         Web Export
              |
              v
       future publishers
```

Publisher interface:

```python
class Publisher:
    def publish(self, media):
        raise NotImplementedError
```

Possible implementations:

```text
InternetArchivePublisher
YouTubePublisher
FilesystemPublisher
```

The core pipeline must not depend on any single publisher.

---

# 22. Rights Layer

Rights are part of the data model.

```text
source
   |
   v
rights_status
   |
   v
publication_policy
```

Example:

```text
unknown
open_license
permission_obtained
source_permitted
restricted
do_not_publish
```

The publisher must check policy before publishing.

The system must not assume that religious/educational content is automatically free to redistribute.

---

# 23. Web Application Architecture

The web application consumes published data.

```text
                    SQLite
                       |
                       v
                  Data Export
                       |
                       v
                lectures.json
                       |
                       v
                 Web Frontend
```

Initial frontend:

```text
HTML
CSS
JavaScript
```

Features:

```text
search
audio player
speaker
Surah
category
tags
date
source
archive link
```

The web application does not control the downloader.

---

# 24. Search Architecture

Initial search:

```text
SQLite FTS5
```

Later:

```text
transcripts
     |
     v
FTS5
     |
     v
semantic search
```

Only introduce embeddings/vector databases if ordinary full-text search proves insufficient.

---

# 25. Future Transcription Layer

Not required for v1.

Future:

```text
             audio
               |
               v
             Whisper
               |
               v
           transcript
          /    |     \
         /     |      \
       FTS5   Qwen   chapters
```

This is where the LLM becomes significantly more valuable.

The transcript can enable:

* topic extraction
* summaries
* chapter generation
* full-text search
* Quran reference detection
* improved tagging

---

# 26. Scheduler

Use Linux `systemd`.

```text
systemd timer
      |
      v
discovery
      |
      v
worker
      |
      v
queue processing
```

No Redis/Celery/Airflow is necessary initially.

---

# 27. Worker Architecture

The worker should process persisted jobs.

```text
             SQLite
                |
                v
          pending jobs
                |
                v
             Worker
                |
        +-------+-------+
        |       |       |
      yt-dlp  FFmpeg   Qwen
        |       |       |
        +-------+-------+
                |
                v
             SQLite
```

The worker can be stopped and restarted.

---

# 28. CLI Architecture

The CLI provides operational control.

```text
tadabbur
├── discover
├── classify
├── download
├── process
├── validate
├── publish
├── worker
├── status
├── failed
├── retry
└── inspect
```

The CLI should call application services rather than duplicate business logic.

---

# 29. Daily Autonomous Flow

Normal operation:

```text
07:00
  |
  v
DISCOVER
  |
  v
new videos
  |
  v
RULE CLASSIFIER
  |
  +---- irrelevant ---> REJECTED
  |
  v
TADABBUR
  |
  v
QUEUE
  |
  v
yt-dlp DOWNLOAD
  |
  v
FFmpeg AUDIO
  |
  v
METADATA
  |
  v
TAGGING
  |
  v
VALIDATION
  |
  v
READY
  |
  +----> Internet Archive
  |
  +----> Web Export
```

---

# 30. Recovery Flow

If the machine crashes:

```text
             MACHINE CRASH
                   |
                   v
               RESTART
                   |
                   v
              SQLite state
                   |
                   v
             find unfinished
                   |
                   v
             validate files
              /          \
           valid         invalid
             |              |
             v              v
          continue        retry
```

No manual reconstruction of the queue should be required.

---

# 31. Security Principles

The system should:

* [ ] never store secrets in source code
* [ ] use environment variables for credentials
* [ ] redact secrets from logs
* [ ] validate all subprocess arguments
* [ ] avoid shell string concatenation
* [ ] use `subprocess` argument arrays
* [ ] validate downloaded paths
* [ ] prevent path traversal
* [ ] restrict writable directories
* [ ] validate downloaded files
* [ ] enforce maximum file sizes where appropriate
* [ ] maintain backups of SQLite
* [ ] maintain checksums for important archival files

---

# 32. Operational Principle

The pipeline should prefer:

```text
slow + reliable
```

over:

```text
fast + fragile
```

For a long-term archive, duplicate prevention, resumability, metadata preservation and integrity are more important than maximizing download speed.

---

# 33. Scaling Path

The architecture intentionally starts simple.

```text
V1
Single Linux machine
SQLite
systemd
yt-dlp
FFmpeg
```

Then potentially:

```text
V2
SQLite
+ API
+ web application
+ transcription
```

Then:

```text
V3
PostgreSQL
multiple workers
object storage
```

Only scale when actual workload requires it.

---

# 34. Final Architecture

```text
                           INTERNET
                              |
                    +---------+---------+
                    |                   |
               YouTube Sources      Other Sources
                    |
                    v
              +-----------+
              |  yt-dlp   |
              +-----+-----+
                    |
                    v
            +---------------+
            |  DISCOVERY    |
            +-------+-------+
                    |
                    v
            +---------------+
            |    SQLite     |
            |               |
            | media         |
            | jobs          |
            | taxonomy      |
            | tags          |
            +-------+-------+
                    |
                    v
            +---------------+
            | RULE ENGINE   |
            +-------+-------+
                    |
             ambiguous?
              /       \
            no         yes
            |           |
            |        +--v---+
            |        | Qwen |
            |        +--+---+
            |           |
            +-----+-----+
                  |
                  v
          +---------------+
          | DOWNLOAD QUEUE|
          +-------+-------+
                  |
                  v
             +---------+
             | yt-dlp  |
             +----+----+
                  |
                  v
             +---------+
             | FFmpeg  |
             +----+----+
                  |
                  v
          +---------------+
          |   VALIDATOR   |
          +-------+-------+
                  |
                  v
          +---------------+
          | MEDIA LIBRARY |
          +-------+-------+
                  |
          +-------+-------+
          |               |
          v               v
 +----------------+  +----------------+
 | Internet       |  | Web Data       |
 | Archive        |  | Export         |
 +----------------+  +-------+--------+
                               |
                               v
                       +---------------+
                       | Tadabbur Web  |
                       | Application   |
                       +---------------+

                  FUTURE
                    |
          +---------+---------+
          |                   |
          v                   v
       Whisper              Qwen
          |                   |
          v                   v
     Transcript        semantic tagging
          |                   |
          +---------+---------+
                    |
                    v
                 FTS5
                    |
                    v
             Advanced Search
```

---

# 35. Architectural Golden Rules

1. **yt-dlp remains the ingestion engine.**
2. **SQLite is the source of truth.**
3. **Every operation is resumable.**
4. **Every important operation is idempotent.**
5. **Rules before AI.**
6. **Qwen is optional, not mandatory.**
7. **A small Qwen model is sufficient for classification.**
8. **Never hallucinate source metadata.**
9. **Keep publishers separate from ingestion.**
10. **Keep the web application separate from the downloader.**
11. **Do not introduce infrastructure before it is needed.**
12. **Use legitimate proxy/network configuration, not anti-bot evasion.**
13. **Use backoff/cooldown rather than aggressive retries.**
14. **Treat rights/publication policy as first-class data.**
15. **Build Tadabbur first; expand the taxonomy later.**
16. **Add transcription only after the ingestion pipeline is reliable.**
17. **Add semantic search only after ordinary search is insufficient.**
18. **Reliability is more important than download speed.**
19. **Every stage must be independently testable.**
20. **The system should recover automatically after crashes/reboots.**

The long-term objective is not merely a downloader.

It is:

```text
        SOURCE
          |
          v
      INGESTION
          |
          v
       ARCHIVE
          |
          v
     KNOWLEDGE BASE
          |
          v
    TADBABBUR LIBRARY
          |
          +---------> Internet Archive
          |
          +---------> Web Application
          |
          +---------> Search
          |
          +---------> Future AI tools
```

The first milestone remains deliberately small:

> **Automatically find new Tadabbur videos, download their audio, catalogue them correctly, survive failures, and make them ready for publication.**

Everything else evolves from that foundation.
