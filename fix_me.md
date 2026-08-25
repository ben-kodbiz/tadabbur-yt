# Uploader Pipeline — Fix Me

## Purpose

This document contains **targeted corrections** for the existing uploader implementation under:

```text
src/tadabbur/uploader/
```

The current architecture is fundamentally sound.

**DO NOT rewrite the uploader.**

Implement the fixes below while preserving existing modules, interfaces, database compatibility, CLI behavior, and working functionality.

The objective is to make the pipeline safer and genuinely resumable before processing hundreds/thousands of recordings.

---

# 1. Critical Rules

The agent MUST follow these rules:

* [ ] Do not rewrite the uploader architecture.
* [ ] Do not replace SQLite.
* [ ] Do not replace the repository pattern.
* [ ] Do not replace the existing state machine.
* [ ] Do not replace yt-dlp.
* [ ] Do not replace FFmpeg.
* [ ] Do not replace the YouTube Data API implementation.
* [ ] Do not introduce Redis.
* [ ] Do not introduce Celery.
* [ ] Do not introduce PostgreSQL.
* [ ] Do not introduce Kubernetes.
* [ ] Do not introduce microservices.
* [ ] Do not add cloud infrastructure.
* [ ] Do not break existing CLI commands.
* [ ] Do not remove existing rights-management states.
* [ ] Do not weaken the upload safety gate.
* [ ] Do not assume attribution equals permission.

Prefer small, isolated changes.

Before modifying a file, understand its existing responsibilities.

---

# 2. Priority Classification

Implement in this order:

```text
P0 — Critical
    1. Rights gate
    2. Artifact-aware resume
    3. MP4 validation
    4. Upload retry safety
    5. Source attribution

P1 — Important
    6. SHA-256 duplicate detection
    7. Processing/upload event history
    8. Archive-vs-YouTube derivative separation

P2 — Useful
    9. Optional MP4 cleanup
    10. Additional reporting
```

Do not start P2 work until P0 is complete and tested.

---

# 3. P0 — Enforce Rights Gate Before Processing

## Problem

The current pipeline protects the YouTube upload queue with rights checks, but processing can happen before the final publishing authorization gate.

This can result in:

```text
MANUAL_REVIEW_REQUIRED
        ↓
download
        ↓
audio processing
        ↓
video rendering
```

The upload queue may eventually block the item, but unnecessary processing has already happened.

## Required behavior

Before automatically downloading/processing an item, evaluate:

```python
rights_status
```

against the existing approved rights set.

Approved states must remain explicitly defined.

For example:

```python
APPROVED_FOR_UPLOAD = {
    PERMISSION_CONFIRMED,
    LICENSE_CONFIRMED,
    PUBLIC_DOMAIN,
    CREATIVE_COMMONS,
    OWNED_BY_OPERATOR,
}
```

Do not invent a new interpretation where attribution alone is considered permission.

## Behavior

If:

```text
rights_status = approved
```

continue.

If:

```text
rights_status = manual_review_required
```

stop automatic publishing processing.

If:

```text
rights_status = upload_not_authorized
```

mark the item blocked.

If an item is intentionally being retained as an archive-only record, support that state without making it uploadable.

## Important

Do not delete blocked records.

They must remain searchable in SQLite.

---

# 4. P0 — Make Resume Truly Artifact-Aware

## Problem

The current pipeline describes itself as resumable, but not every processing stage independently checks whether its artifact already exists and is valid.

The pipeline must be safe to restart after:

* power loss
* process crash
* FFmpeg failure
* network failure
* system reboot
* manual interruption

## Required behavior

Every stage must follow this pattern:

```text
Does expected artifact exist?
        │
        ├── NO → perform operation
        │
        └── YES
             │
             ▼
        validate artifact
             │
        ┌────┴────┐
        │         │
      valid     invalid
        │         │
        ▼         ▼
      SKIP      rebuild
```

---

## Download

Before downloading:

```text
original file exists?
```

If yes:

```text
validate file
```

If valid:

```text
skip download
```

If invalid:

```text
remove/rename corrupt partial artifact
redownload
```

Do not blindly download again.

---

## Audio

Before running audio processing:

```text
processed Opus exists?
```

Validate:

* file exists
* file size reasonable
* duration valid
* expected codec
* expected channels
* expected sample rate where practical

If valid:

```text
skip processing
```

---

## Video

Before rendering:

```text
YouTube MP4 exists?
```

Run full MP4 validation.

If valid:

```text
skip rendering
```

If invalid:

```text
render again
```

---

# 5. P0 — Add Independent YouTube MP4 Validation

## Problem

Rendering success is not sufficient evidence that the resulting MP4 is suitable for upload.

A video can be generated but still be:

* corrupt
* missing an audio stream
* missing a video stream
* incorrectly encoded
* truncated
* wrong duration
* wrong dimensions

## Required module

Prefer extending the existing validator rather than creating unnecessary duplicate validation infrastructure.

Possible location:

```text
src/tadabbur/uploader/validator.py
```

or the existing validation module if one already exists.

Create a function conceptually equivalent to:

```python
validate_youtube_video(path, expected_duration=None)
```

It must use `ffprobe`.

## Validate

At minimum:

```text
container = MP4
video stream exists
audio stream exists
video codec = H.264
audio codec = AAC
video width = expected
video height = expected
duration > 0
file size > minimum
```

Also compare duration:

```text
abs(source_duration - output_duration) <= configured_tolerance
```

Use a configurable tolerance rather than exact equality.

---

# 6. Correct Processing State Flow

The final processing flow should become:

```text
DOWNLOADED
    ↓
AUDIO_PROCESSING
    ↓
AUDIO_READY
    ↓
VIDEO_RENDERING
    ↓
VALIDATION
    ↓
    ┌───────────────┐
    │               │
 VALID             INVALID
    │               │
    ▼               ▼
READY_FOR_UPLOAD  PROCESSING_RETRY
```

Do not transition directly:

```text
VIDEO_RENDERING
      ↓
READY_FOR_UPLOAD
```

without validation.

---

# 7. P0 — Improve Upload Retry Safety

## Problem

YouTube resumable uploads can fail ambiguously.

A network failure does not always prove that YouTube rejected the upload.

This creates a duplicate-upload risk:

```text
upload succeeds remotely
        ↓
client loses response
        ↓
client thinks upload failed
        ↓
retry
        ↓
duplicate video
```

## Required changes

Preserve the existing resumable upload implementation.

Add persistent upload attempt information.

At minimum record:

```text
upload attempt ID
media item ID
upload started time
upload status
attempt number
error category
```

Where possible, preserve the resumable upload session information.

---

# 8. Upload Must Remain Idempotent

Before creating a new upload attempt:

```text
Does database already contain platform_video_id?
```

If yes:

```text
DO NOT upload again.
```

Instead:

```text
mark uploaded
```

after verifying the record.

Also check whether an upload record already indicates successful completion.

---

# 9. Ambiguous Upload Failures

Classify upload failures.

At minimum:

```text
AUTH_ERROR
QUOTA_ERROR
NETWORK_ERROR
TIMEOUT
SERVER_ERROR
INVALID_REQUEST
FILE_ERROR
UNKNOWN_ERROR
```

Only retry errors that are reasonably retryable.

Do not endlessly retry:

```text
invalid request
authorization failure
quota exhaustion
invalid metadata
```

These should require intervention or a later scheduled retry.

---

# 10. P0 — Source Attribution Must Exist in the Video

The YouTube description already carries source information.

Strengthen the rendered video itself.

The visual should clearly indicate that the recording originates elsewhere.

Example:

```text
ORIGINAL RECORDING

Speaker:
{speaker_name}

Original Source:
{source_name}

This channel is collecting and organizing
recordings from the original source.

No authorship of the original recording is claimed.

Original link:
See description
```

Do not claim:

```text
Used with permission
```

unless the database actually records that permission.

Do not imply ownership.

---

# 11. Preserve Full Provenance in Description

The description must contain:

```text
original title
original speaker/channel
original URL
source channel URL
rights status where appropriate
permission/license information where applicable
archive/collection disclaimer
contact/removal mechanism
```

Do not remove the existing attribution mechanism.

---

# 12. P1 — Add SHA-256 Duplicate Detection

Current:

```text
platform + original_media_id
```

is the primary identity.

Keep it.

Add:

```text
original_sha256
```

to detect exact duplicate recordings that have different platform IDs.

For example:

```text
YouTube video A
ID = ABC123
SHA256 = XYZ

YouTube video B
ID = DEF456
SHA256 = XYZ
```

The system should detect:

```text
possible exact duplicate
```

and flag it.

Do NOT automatically delete either item.

---

# 13. Database Migration

Add a migration mechanism if the project does not already have one.

Do not destroy existing databases.

For example:

```text
schema version 1
        ↓
migration
        ↓
schema version 2
```

Never require the user to delete:

```text
pipeline.db
```

to obtain the new schema.

Backwards compatibility is important because the database contains the upload history.

---

# 14. P1 — Add Event/Audit History

Current state fields tell us where an item is now.

Add an optional audit table:

```sql
media_events
```

Suggested schema:

```sql
CREATE TABLE media_events (
    id INTEGER PRIMARY KEY,
    media_item_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT,
    message TEXT,
    error_category TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(media_item_id)
        REFERENCES media_items(id)
);
```

Record important events:

```text
DISCOVERED
RIGHTS_APPROVED
RIGHTS_BLOCKED
DOWNLOAD_STARTED
DOWNLOAD_COMPLETED
AUDIO_STARTED
AUDIO_COMPLETED
VIDEO_STARTED
VIDEO_COMPLETED
VALIDATION_FAILED
UPLOAD_STARTED
UPLOAD_COMPLETED
UPLOAD_FAILED
RETRY_SCHEDULED
```

Do not log secrets or OAuth tokens.

---

# 15. P1 — Separate Archive Audio From YouTube Delivery Video

Make the distinction explicit.

The pipeline produces two different derivatives:

```text
ORIGINAL
   │
   ├───────────────► ARCHIVE AUDIO
   │                  .opus
   │                  48 kbps mono
   │
   └───────────────► YOUTUBE DELIVERY
                      .mp4
                      H.264 + AAC
```

The Opus file is the compact archival derivative.

The MP4 is the YouTube delivery artifact.

Do not repeatedly transcode:

```text
Opus → MP4 → Opus
```

Always derive new outputs from the best available original source.

---

# 16. Storage Cleanup

Add optional configuration:

```yaml
storage:
  keep_originals: true
  keep_processed_audio: true
  keep_youtube_mp4_after_upload: true
  delete_temp_after_success: true
```

Default:

```text
keep_originals = true
keep_processed_audio = true
keep_youtube_mp4_after_upload = true
```

Do not automatically delete the MP4 in the first implementation.

Once the pipeline has been proven stable, allow:

```yaml
keep_youtube_mp4_after_upload: false
```

But only delete it after:

```text
upload successful
+
platform_video_id stored
+
database transaction committed
```

---

# 17. Don't Change the Audio Strategy

The existing speech-oriented Opus approach is good.

Keep:

```text
Opus
mono
48 kHz
configurable bitrate
```

Recommended default:

```text
48 kbps
```

Do not unnecessarily increase the bitrate.

Do not optimize for the absolute smallest possible file at the expense of speech intelligibility.

---

# 18. Don't Change the YouTube API Architecture

Keep:

```text
YouTube Data API
+
resumable upload
+
chunked upload
```

Do NOT replace it with:

```text
Selenium
Playwright
Puppeteer
browser automation
```

unless there is a separate future requirement.

---

# 19. Upload Safety Controls

Preserve the existing safety mechanisms.

Ensure configuration supports:

```yaml
upload:
  enabled: false
  require_manual_enable: true
  max_uploads_per_run: 3
  max_uploads_per_day: 5
  dry_run_default: true
```

The exact numbers may remain configurable.

The important rule is:

```text
NO MASS UPLOAD BY ACCIDENT
```

A cron job must never suddenly upload hundreds of recordings because a state-transition bug occurred.

---

# 20. Queue Safety

Before an item enters:

```text
UPLOAD_QUEUED
```

verify:

```text
rights approved
original exists
archive audio valid
YouTube MP4 valid
metadata valid
no existing platform_video_id
```

If any check fails:

```text
do not queue
```

Record the reason.

---

# 21. Final Upload Gate

Immediately before upload, run one final validation.

Conceptually:

```python
assert rights_approved(item)
assert original_exists(item)
assert archive_audio_valid(item)
assert youtube_video_valid(item)
assert metadata_valid(item)
assert not already_uploaded(item)
```

Only then:

```text
UPLOAD
```

This is intentional defense-in-depth.

---

# 22. CLI Compatibility

Existing CLI commands must continue to work.

Do not rename or remove commands unless absolutely necessary.

Add commands only where useful.

Recommended:

```bash
pipeline validate <id>
pipeline events <id>
pipeline duplicates
pipeline queue list
pipeline retry failed
```

Optional:

```bash
pipeline repair <id>
```

The repair command should inspect artifacts and reconstruct the correct state where possible.

---

# 23. `repair` Command

This would be especially useful after crashes.

Example:

```bash
pipeline repair 123
```

It should inspect:

```text
database state
original file
Opus file
MP4 file
metadata
upload record
```

Then report:

```text
Database state: VIDEO_RENDERING
Original: VALID
Audio: VALID
Video: VALID
Upload: NOT STARTED

Recommended state:
READY_FOR_UPLOAD
```

It should not silently modify data unless explicitly requested.

Optional:

```bash
pipeline repair 123 --apply
```

---

# 24. Testing Requirements

Do not consider this complete without tests.

## Rights tests

* [ ] approved rights can proceed
* [ ] unknown rights blocked
* [ ] manual review blocked
* [ ] unauthorized blocked
* [ ] archive-only remains non-uploadable

## Duplicate tests

* [ ] same YouTube ID rejected
* [ ] same SHA-256 flagged
* [ ] different titles with same source ID handled correctly

## Audio tests

* [ ] valid Opus accepted
* [ ] corrupt Opus rejected
* [ ] wrong codec rejected
* [ ] invalid duration rejected

## Video tests

* [ ] valid MP4 accepted
* [ ] missing audio rejected
* [ ] missing video rejected
* [ ] wrong codec rejected
* [ ] wrong resolution rejected
* [ ] duration mismatch rejected
* [ ] corrupt MP4 rejected

## Resume tests

Simulate:

```text
crash after download
crash after audio
crash after rendering
crash before database state update
```

Then rerun.

The pipeline should reuse valid artifacts instead of unnecessarily rebuilding them.

## Upload tests

Simulate:

```text
network failure
timeout
HTTP 5xx
invalid credentials
existing platform_video_id
ambiguous upload failure
```

Ensure no obvious duplicate-upload path is introduced.

---

# 25. Test With a Tiny Dataset First

Before processing the full collection:

```text
1 recording
```

Then:

```text
3 recordings
```

Then:

```text
10 recordings
```

Only after successful testing:

```text
100+
```

Do NOT start with the entire collection.

---

# 26. Recommended Test Scenario

Use one known recording.

Run:

```bash
pipeline discover
```

Then approve it appropriately.

Run:

```bash
pipeline process pending
```

Verify:

```text
original
audio.opus
youtube.mp4
metadata
database
```

Then deliberately interrupt the process.

Run again.

Expected behavior:

```text
original → reused
audio.opus → reused
youtube.mp4 → reused
```

Then upload with:

```bash
pipeline upload run --limit 1 --dry-run
```

Review everything.

Only then perform the real upload.

---

# 27. Logging

Every important operation should produce structured logs.

Example:

```text
2026-08-25 10:21:02 INFO  media=123 stage=audio status=started
2026-08-25 10:21:15 INFO  media=123 stage=audio status=completed
2026-08-25 10:21:16 INFO  media=123 stage=video status=started
2026-08-25 10:22:04 INFO  media=123 stage=video status=completed
2026-08-25 10:22:05 INFO  media=123 stage=validation status=passed
```

Errors should contain:

```text
media ID
stage
exception
error category
attempt
```

Never log:

```text
OAuth tokens
refresh tokens
client secrets
passwords
```

---

# 28. Error Recovery Principle

Never use:

```python
except Exception:
    pass
```

and never silently convert failures into successful states.

Every failure must become one of:

```text
retry
blocked
manual_review
failed
```

with a reason.

---

# 29. Definition of Done

The fix is complete only when all of the following are true:

* [ ] Rights gate prevents unauthorized processing/upload.
* [ ] Valid existing artifacts are reused.
* [ ] Invalid artifacts are regenerated.
* [ ] MP4 receives independent validation.
* [ ] READY_FOR_UPLOAD requires validation success.
* [ ] Existing uploads cannot be uploaded again.
* [ ] Upload attempts are recorded.
* [ ] Retry behavior distinguishes retryable/non-retryable failures.
* [ ] SHA-256 duplicate detection exists.
* [ ] Source attribution appears in YouTube metadata.
* [ ] Source attribution is visible in the rendered video.
* [ ] Database migrations preserve existing data.
* [ ] Event history records important transitions.
* [ ] Existing CLI behavior remains functional.
* [ ] Existing tests still pass.
* [ ] New tests cover the fixes.
* [ ] A crash/resume test succeeds.
* [ ] A duplicate-upload test succeeds.
* [ ] A corrupt-MP4 test succeeds.

---

# 30. Final Architecture After Fixes

The final flow should be:

```text
                 ┌──────────────────┐
                 │     DISCOVER     │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ RECORD PROVENANCE│
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │   RIGHTS GATE    │
                 └───────┬──────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
          NOT APPROVED           APPROVED
              │                     │
              ▼                     ▼
          BLOCK/ARCHIVE          DOWNLOAD
                                    │
                                    ▼
                             ORIGINAL VALID?
                                    │
                                    ▼
                             AUDIO PROCESSING
                                    │
                                    ▼
                              OPUS VALID?
                                    │
                                    ▼
                             VIDEO RENDERING
                                    │
                                    ▼
                              MP4 VALIDATION
                                    │
                           ┌────────┴────────┐
                           │                 │
                         FAIL              PASS
                           │                 │
                           ▼                 ▼
                         RETRY        READY_FOR_UPLOAD
                                             │
                                             ▼
                                      FINAL VALIDATION
                                             │
                                             ▼
                                      UPLOAD QUEUE
                                             │
                                             ▼
                                      YOUTUBE UPLOAD
                                             │
                                             ▼
                                    VERIFY VIDEO ID
                                             │
                                             ▼
                                         UPLOADED
```

---

# 31. Most Important Instruction to the Coding Agent

**Do not rewrite what already works.**

This project is now at the stage where incremental hardening is more valuable than architectural experimentation.

Make the smallest changes necessary to achieve:

```text
correct rights gating
+
true resume
+
strong validation
+
duplicate protection
+
safe uploads
+
complete provenance
```

After implementation, provide a concise report containing:

```text
Files modified:
Database migrations:
New functions:
New tests:
Existing tests:
Known limitations:
```

Also explicitly state whether each P0 item was completed.
