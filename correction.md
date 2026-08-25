Below is a `correction.md` designed for your agentic coding workflow. It is intentionally **additive and non-destructive**: preserve the existing architecture, fix the concrete weaknesses, and validate every stage before moving on.

````markdown
# TADABBUR-YT — CORRECTION & RELIABILITY PLAN

## Purpose

This document defines corrections and improvements for the existing
`tadabbur-yt` codebase.

The project already has a good architecture. **DO NOT rewrite it.**

The objective is to:

1. Fix resumable download behaviour.
2. Fix proxy configuration precedence.
3. Prevent single-video commands from processing unrelated videos.
4. Normalize yt-dlp timeout failures.
5. Prevent overlapping workers.
6. Clarify retry ownership.
7. Improve crash/reboot recovery.
8. Verify configuration options actually work.
9. Improve discovery efficiency over time.
10. Improve CI and operational visibility.
11. Preserve deterministic classification.
12. Keep Qwen disabled unless real production data proves it is needed.

---

# 0. NON-DESTRUCTIVE RULES

Before making any changes:

- [ ] Read the existing architecture and implementation.
- [ ] Do not rename modules without a strong reason.
- [ ] Do not replace SQLite with another database.
- [ ] Do not add Redis.
- [ ] Do not add Celery.
- [ ] Do not add Kubernetes.
- [ ] Do not introduce a web framework rewrite.
- [ ] Do not replace the existing repository pattern.
- [ ] Do not remove working tests.
- [ ] Do not change existing public interfaces unnecessarily.
- [ ] Prefer small isolated commits.
- [ ] Add tests before or together with behavioural changes.
- [ ] Run the full test suite after every stage.
- [ ] Preserve backward compatibility for existing configuration where practical.

The architecture should evolve like this:

```text
CURRENT WORKING SYSTEM
        │
        ▼
SMALL ISOLATED FIX
        │
        ▼
TEST
        │
        ▼
COMMIT
        │
        ▼
NEXT FIX
````

Never perform a large "cleanup" that combines unrelated changes.

---

# 1. FIX RESUMABLE DOWNLOADS

## Problem

The current yt-dlp implementation uses:

```text
--no-part
```

This conflicts with the requirement for intelligent interruption and
resumption.

Without part files, an interrupted download may have to restart instead
of continuing from existing downloaded data.

The pipeline must support:

```text
Download starts
      │
      ▼
Partial data written
      │
      ├── network failure
      ├── process crash
      ├── machine reboot
      └── manual interruption
             │
             ▼
          .part file
             │
             ▼
      next pipeline run
             │
             ▼
       yt-dlp resumes
```

## Required Changes

### 1.1 Add explicit resume configuration

Inspect the existing configuration structure.

Add resume-related settings without breaking existing configuration.

Suggested structure:

```yaml
download:
  resume: true
  keep_part_files: true
```

If an equivalent configuration already exists, reuse it instead of
creating duplicate settings.

### 1.2 Change yt-dlp argument construction

Do not always add:

```text
--no-part
```

Desired behaviour:

```text
download.resume = true
        │
        ▼
allow .part files
        │
        ▼
yt-dlp can resume
```

```text
download.resume = false
        │
        ▼
--no-part may be used
```

Pseudo-code only:

```python
if not settings.download.resume:
    args.append("--no-part")
```

Do not duplicate command-building logic across methods.

Prefer centralizing this behaviour in the existing yt-dlp argument
builder.

### 1.3 Validate partial downloads

Do not consider the presence of a final filename sufficient proof that
the file is valid.

The recovery flow should distinguish:

```text
final media file
.part file
temporary conversion file
corrupted/incomplete file
missing file
```

### 1.4 Add tests

Add tests for:

* [ ] Resume enabled does not add `--no-part`.
* [ ] Resume disabled adds `--no-part`.
* [ ] Interrupted download can be retried.
* [ ] Existing `.part` file does not create a duplicate job.
* [ ] Recovery logic correctly identifies incomplete state.

## Acceptance Criteria

```text
interrupt download
      ↓
restart worker
      ↓
same video is claimed
      ↓
yt-dlp continues safely
      ↓
successful completion
```

---

# 2. FIX PROXY PRECEDENCE AND DUPLICATION

## Problem

The current yt-dlp client can potentially add `--proxy` more than once.

Example:

```text
--proxy CONFIG_PROXY
...
--proxy METHOD_PROXY
```

This creates ambiguous configuration ownership.

There must be exactly one effective proxy for a single yt-dlp operation.

## Required Design

Determine the effective proxy once.

Priority:

```text
Per-operation override
        │
        ▼
Configured proxy
        │
        ▼
No proxy
```

Suggested conceptual helper:

```python
def get_effective_proxy(
    settings_proxy,
    override_proxy=None,
):
    if override_proxy:
        return override_proxy

    if settings_proxy.enabled and settings_proxy.url:
        return settings_proxy.url

    return None
```

Then:

```text
effective_proxy
       │
       ▼
add --proxy exactly once
```

## Required Changes

* [ ] Inspect `_base_args()`.
* [ ] Inspect every download method.
* [ ] Inspect metadata extraction commands.
* [ ] Inspect playlist/channel discovery commands.
* [ ] Ensure no operation can accidentally inject two proxy arguments.
* [ ] Preserve per-operation proxy override if it already exists.
* [ ] Keep proxy configuration centralized.

## Add Tests

* [ ] Config proxy only.
* [ ] Override proxy only.
* [ ] Override takes precedence.
* [ ] Disabled proxy produces no `--proxy`.
* [ ] No duplicate `--proxy` arguments.

## Acceptance Criteria

For every yt-dlp invocation:

```text
proxy arguments count <= 1
```

---

# 3. FIX SINGLE-VIDEO PIPELINE SCOPE

## Problem

A command intended to process one video may invoke general batch
services.

Example intention:

```bash
tadabbur process VIDEO_A
```

Potential bad behaviour:

```text
VIDEO_A requested
     │
     ▼
general classifier runs
     │
     ├── VIDEO_A
     ├── VIDEO_B
     ├── VIDEO_C
     └── VIDEO_D
```

A single-video operation must not unexpectedly process unrelated work.

## Required Design

Batch mode:

```python
run_classification(settings)
```

Single-video mode:

```python
run_classification(
    settings,
    video_id=video_id,
)
```

The same principle applies to:

* classification
* downloading
* audio conversion
* metadata extraction
* tagging
* validation
* publishing, where applicable

## Required Changes

### 3.1 Inspect all pipeline services

Identify services that currently process all eligible rows.

Examples may include:

```text
run_classification()
run_tagging()
run_downloads()
run_validation()
run_publish()
```

Do not rename them unnecessarily.

Add optional filtering only where required:

```python
video_id: str | None = None
```

### 3.2 Repository-level filtering

Prefer filtering at the database query level.

Good:

```text
SELECT ...
WHERE video_id = ?
AND status = ?
```

Avoid:

```text
SELECT all pending rows
        ↓
load everything
        ↓
filter in Python
```

### 3.3 Preserve batch behaviour

When `video_id is None`, existing batch behaviour must remain unchanged.

## Add Tests

* [ ] Process one video.
* [ ] Verify unrelated pending videos are untouched.
* [ ] Batch mode still processes eligible videos.
* [ ] Invalid video ID produces a useful error.
* [ ] State transitions remain valid.

## Acceptance Criteria

```bash
tadabbur process VIDEO_A
```

must only affect `VIDEO_A`, except for unavoidable shared read-only
operations such as loading configuration.

---

# 4. NORMALIZE SUBPROCESS TIMEOUT FAILURES

## Problem

`subprocess.run(..., timeout=N)` can raise:

```text
subprocess.TimeoutExpired
```

If this escapes directly, timeout failures follow a different error path
from ordinary yt-dlp failures.

The retry/recovery system should receive a consistent domain-level error.

## Required Change

Catch:

```python
subprocess.TimeoutExpired
```

Convert it into the project's existing yt-dlp/domain exception type.

Conceptual example:

```python
try:
    subprocess.run(...)
except subprocess.TimeoutExpired as exc:
    raise YtDlpError(
        f"yt-dlp timed out after {timeout} seconds"
    ) from exc
```

Do not expose huge command output unnecessarily.

Preserve useful diagnostic information where safe.

## Add Tests

* [ ] Simulated subprocess timeout.
* [ ] Correct domain exception raised.
* [ ] Retry manager recognizes it as retryable where appropriate.
* [ ] Final failure state is recorded after retry exhaustion.

## Acceptance Criteria

```text
yt-dlp timeout
      ↓
domain error
      ↓
retry/backoff decision
      ↓
success OR controlled failure state
```

No uncaught timeout exception should crash the worker unexpectedly.

---

# 5. PREVENT OVERLAPPING WORKERS

## Problem

A scheduled worker can overlap with a previous run.

Example:

```text
08:00 worker starts
08:30 long download still running
09:00 timer triggers another worker
09:00 duplicate worker starts
```

Possible consequences:

* duplicate downloads
* competing state transitions
* unnecessary network usage
* confusing logs
* race conditions

## Preferred Solution

Implement one of these approaches with minimal architectural change.

### Option A — Process-level lock

Use a lock file.

Example:

```text
data/
└── worker.lock
```

Flow:

```text
worker starts
    │
    ▼
acquire lock
    │
    ├── lock available → continue
    │
    └── lock held → exit safely
```

Ensure stale locks are handled correctly.

Do not simply create a permanent file without ownership checking.

### Option B — systemd service architecture

If systemd deployment is already supported, prefer a long-running service
when appropriate:

```text
systemd
   │
   ▼
single worker process
   │
   ├── scheduled discovery
   ├── download queue
   └── recovery loop
```

Do not introduce this if the existing timer architecture is already
simpler and reliable.

## Add Tests

* [ ] First worker acquires lock.
* [ ] Second worker exits safely.
* [ ] Lock released on normal shutdown.
* [ ] Lock released/cleaned after abnormal termination where possible.

## Acceptance Criteria

At most one pipeline worker performs active work at a time.

---

# 6. CLARIFY RETRY OWNERSHIP

## Problem

The project has both:

```text
yt-dlp retries
```

and:

```text
application-level retries/backoff
```

These can multiply.

Example:

```text
Application attempt 1
    └── yt-dlp retries multiple times

Application attempt 2
    └── yt-dlp retries multiple times

Application attempt 3
    └── yt-dlp retries multiple times
```

This can cause extremely long blocking failures.

## Required Design

Define clear responsibility.

Recommended:

```text
yt-dlp
 ├── fragment retries
 └── short transport retries

application
 ├── full job retries
 ├── exponential backoff
 ├── cooldown
 └── circuit breaker
```

## Required Changes

* [ ] Document retry ownership.
* [ ] Inspect existing retry counts.
* [ ] Avoid accidental multiplication.
* [ ] Keep retry configuration centralized.
* [ ] Ensure retryable and non-retryable errors are distinguished.

Potential categories:

```text
RETRYABLE
---------
temporary network failure
timeout
temporary proxy failure
temporary upstream failure

NOT RETRYABLE
-------------
invalid URL
unsupported media
permanent configuration error
missing executable
invalid database schema
```

Do not hard-code categories without inspecting the existing error model.

## Add Tests

* [ ] Retryable error retries.
* [ ] Non-retryable error fails immediately.
* [ ] Backoff is applied.
* [ ] Maximum attempts respected.
* [ ] Retry exhaustion creates controlled failure state.

---

# 7. PERSIST CIRCUIT BREAKER STATE

## Problem

The current circuit breaker is process-memory only.

Current behaviour may be:

```text
repeated failures
      ↓
circuit opens
      ↓
machine/process restarts
      ↓
circuit state forgotten
      ↓
immediate retry storm
```

For an autonomous system, cooldown should survive restarts.

## Required Design

Do not redesign the entire database.

Add a small persistent state table only if the existing schema has no
suitable equivalent.

Suggested concept:

```text
circuit_state
-------------------------
name
state
failure_count
cooldown_until
updated_at
```

Possible state:

```text
CLOSED
OPEN
HALF_OPEN
```

## Recovery Behaviour

```text
worker starts
      │
      ▼
load circuit state
      │
      ├── CLOSED → normal operation
      │
      ├── OPEN + cooldown active
      │       ↓
      │    wait/skip
      │
      └── cooldown expired
              ↓
           HALF_OPEN
              ↓
         limited test
              ↓
      success → CLOSED
      failure → OPEN
```

## Important

Do not persist every minor transient failure forever.

Persist only the state required for autonomous recovery.

## Add Tests

* [ ] State survives repository reopen.
* [ ] Cooldown survives simulated restart.
* [ ] Expired cooldown enters recovery path.
* [ ] Successful operation closes circuit.

---

# 8. VERIFY PROXY HEALTH CHECK CONFIGURATION

## Problem

The configuration contains proxy health-check options.

A configuration option must either:

1. affect real runtime behaviour, or
2. not exist.

Dead configuration creates false confidence.

## Required Investigation

Trace configuration from:

```text
config file
    ↓
settings object
    ↓
runtime consumer
    ↓
actual health check
```

Verify whether all settings are used.

Examples:

```yaml
proxy:
  health_check: true
  health_check_timeout: 10
```

## Required Behaviour

If enabled:

```text
before download/discovery
        │
        ▼
proxy connectivity check
        │
        ├── healthy → continue
        │
        └── unhealthy
                ↓
          controlled retry/
          cooldown/failure
```

The health check should be conservative and should not become a
complicated anti-detection mechanism.

It is for reliability, not evasion.

## Add Tests

* [ ] Health check enabled.
* [ ] Healthy proxy passes.
* [ ] Unhealthy proxy fails clearly.
* [ ] Timeout respected.
* [ ] Disabled health check does not run.

If the feature is not implemented and is not needed now:

* [ ] Remove or clearly mark the configuration as unsupported.

---

# 9. ADD SOURCE SYNC STATE

## Priority

MEDIUM / FUTURE-SAFE.

Do not over-engineer if current discovery is small.

## Problem

As channels grow, repeatedly scanning large historical lists becomes
inefficient.

## Recommended State

```text
source_sync_state
-------------------------
source_id
last_success_at
last_seen_video_id
last_error
consecutive_failures
updated_at
```

## Desired Flow

```text
scheduled sync
      │
      ▼
load source state
      │
      ▼
fetch recent entries
      │
      ▼
compare against known database IDs
      │
      ├── new → insert
      │
      └── known history reached
               ↓
            stop
      │
      ▼
record successful sync
```

## Important

Do not rely solely on upload date.

Videos can be:

* reordered
* re-uploaded
* made public later
* modified

Video IDs remain the primary identity.

---

# 10. ADD SINGLE-INSTANCE AND JOB-CLAIM PROTECTION

A worker lock prevents multiple workers globally.

The database should also safely claim individual jobs where practical.

Desired pattern:

```text
PENDING
   │
   ▼
atomic claim
   │
   ▼
PROCESSING
   │
   ├── success → next state
   │
   └── failure → retry/failed
```

Avoid:

```text
worker A reads PENDING
worker B reads PENDING
worker A starts
worker B starts same job
```

If existing repository/state-machine code already supports atomic claiming,
preserve and strengthen it rather than replacing it.

---

# 11. IMPROVE CRASH AND REBOOT RECOVERY

The pipeline should be restart-safe.

On startup:

```text
START
  │
  ▼
inspect database
  │
  ▼
find interrupted PROCESSING jobs
  │
  ├── file complete?
  │       └── validate → advance
  │
  ├── .part exists?
  │       └── return to resumable download
  │
  ├── temporary file?
  │       └── cleanup/recover safely
  │
  └── nothing exists?
          └── retry from appropriate state
```

Do not blindly reset all `PROCESSING` jobs to `PENDING`.

Preserve enough information to understand what happened.

## Add Tests

Simulate:

* [ ] Process crash during download.
* [ ] Reboot during conversion.
* [ ] Crash after download but before DB update.
* [ ] Crash after DB update but before next stage.
* [ ] Recovery does not duplicate output.

---

# 12. ADD PIPELINE METRICS AND STATISTICS

Do not add Prometheus/Grafana unless there is a real need.

Start with SQLite-backed or report-generated metrics.

Track:

```text
sources scanned
videos discovered
videos classified
Tadabbur matches
non-matches
ambiguous items
downloads completed
downloads resumed
downloads failed
average download duration
audio conversions completed
validation failures
retry counts
proxy failures
```

This is especially important for the Qwen decision.

---

# 13. KEEP QWEN DISABLED FOR NOW

## Current Principle

Use deterministic rules first.

```text
TITLE
  │
  ▼
rules / regex / keywords
  │
  ├── confident → classify
  │
  └── ambiguous → manual review / future LLM
```

Do not invoke a 2B/3B model for obvious titles.

Example:

```text
Tadabbur Surah Al-Baqarah Sesi 15
```

A rule is faster, cheaper and more reliable.

## Required Changes

Do not make Qwen mandatory.

Keep:

```yaml
classification:
  qwen_enabled: false
```

or the existing equivalent.

Before enabling Qwen, collect real statistics.

Suggested report:

```text
Classification Report
---------------------

Total discovered:        N
Rules matched:           N
Rules rejected:          N
Ambiguous/manual review: N
Rule accuracy:           %
```

## Future Qwen Trigger

Only consider Qwen when:

```text
ambiguous classification rate
        OR
manual review workload
        OR
semantic tagging requirement
```

becomes significant.

If added later:

```text
RULES
  │
  ├── confident → result
  │
  └── uncertain
          │
          ▼
       Qwen fallback
          │
          ▼
       confidence
          │
          ├── high → accept
          └── low → manual review
```

---

# 14. ADD CI

The test suite should run automatically.

Recommended minimal workflow:

```text
GitHub Actions
      │
      ▼
checkout
      │
      ▼
Python version matrix
      │
      ▼
pip install -e ".[dev]"
      │
      ▼
pytest
```

Use the project's actual supported Python versions.

Do not add unnecessary services.

## Suggested Checks

* [ ] Package installation succeeds.
* [ ] Full tests pass.
* [ ] Basic import check passes.
* [ ] Optional lint/type checks only if tooling already exists.

Avoid introducing five new quality tools in one change.

---

# 15. IMPROVE CONFIGURATION VALIDATION

Every configuration option should have:

```text
config
   ↓
schema/model validation
   ↓
runtime use
```

Validate:

* yt-dlp executable/path
* ffmpeg availability
* database path
* output directories
* proxy URL when enabled
* retry values
* timeout values
* Internet Archive configuration when publishing enabled

A bad configuration should fail early with a useful error.

Example:

```text
ERROR: proxy.enabled is true but proxy.url is empty
```

not:

```text
ERROR: subprocess failed
```

---

# 16. ADD OPERATIONAL DIAGNOSTICS

The existing diagnose capability should evolve into a simple health report.

Suggested command:

```bash
tadabbur diagnose
```

It should check:

```text
[OK] Python environment
[OK] Database reachable
[OK] yt-dlp available
[OK] FFmpeg available
[OK] Output directory writable
[OK] Configuration valid
[OK/WARN] Proxy reachable
[OK/WARN] Circuit breaker state
[OK/WARN] Interrupted jobs found
```

Warnings should not automatically mean the whole application is broken.

---

# 17. LOG EVENTS, NOT JUST ERRORS

Logs should make recovery understandable.

Useful event fields:

```text
timestamp
video_id
source_id
stage
old_state
new_state
attempt
error_type
error_message
duration
```

Example conceptual event:

```text
video=abc123
stage=download
attempt=2
event=retry
reason=timeout
next_retry=60s
```

Avoid logging secrets:

* proxy credentials
* API credentials
* Internet Archive secrets
* tokens

---

# 18. DO NOT ADD LLM TO AUDIO CATALOGING YET

The current focus is:

```text
TADABBUR
```

Metadata already provides substantial information:

* title
* description
* uploader/channel
* upload date
* playlist
* duration
* video ID
* series/session number

Use deterministic extraction first.

Suggested hierarchy:

```text
SOURCE
  │
  ├── ustaz/preacher
  └── channel
        │
        ▼
CONTENT TYPE
  │
  └── Tadabbur
        │
        ▼
SERIES
  │
  └── Surah/topic
        │
        ▼
SESSION
  │
  └── number/date
        │
        ▼
TAGS
```

Only add semantic LLM tagging after the deterministic taxonomy has been
proven insufficient.

---

# 19. IMPLEMENTATION ORDER

## Stage 1 — Critical Download Reliability

* [ ] Add configurable resume behaviour.
* [ ] Stop unconditional `--no-part`.
* [ ] Test `.part` recovery.
* [ ] Normalize timeout exceptions.
* [ ] Run full tests.

**Commit after completion.**

Suggested commit:

```text
fix(download): restore resumable yt-dlp downloads
```

---

## Stage 2 — Proxy Correctness

* [ ] Trace all proxy injection points.
* [ ] Create one effective-proxy decision.
* [ ] Ensure one `--proxy` maximum.
* [ ] Test precedence.
* [ ] Verify health-check configuration.

**Commit after completion.**

Suggested commit:

```text
fix(proxy): centralize proxy precedence and validation
```

---

## Stage 3 — Pipeline Scope

* [ ] Audit single-video commands.
* [ ] Add optional `video_id` filtering.
* [ ] Filter at repository query level.
* [ ] Verify unrelated videos remain untouched.
* [ ] Preserve batch mode.

**Commit after completion.**

Suggested commit:

```text
fix(pipeline): restrict single-video processing scope
```

---

## Stage 4 — Worker Reliability

* [ ] Add single-instance protection.
* [ ] Review job claiming.
* [ ] Test concurrent-start behaviour.
* [ ] Improve interrupted job recovery.

**Commit after completion.**

Suggested commit:

```text
fix(worker): prevent overlapping pipeline execution
```

---

## Stage 5 — Retry and Circuit Recovery

* [ ] Document retry ownership.
* [ ] Prevent excessive nested retries.
* [ ] Persist circuit breaker state.
* [ ] Ensure cooldown survives restart.
* [ ] Test restart recovery.

**Commit after completion.**

Suggested commit:

```text
fix(recovery): persist retry and circuit-breaker state
```

---

## Stage 6 — Discovery Efficiency

* [ ] Add source sync state if needed.
* [ ] Track last successful sync.
* [ ] Track consecutive failures.
* [ ] Preserve video-ID identity.
* [ ] Test incremental discovery.

**Commit after completion.**

Suggested commit:

```text
feat(discovery): persist incremental source sync state
```

---

## Stage 7 — Operations

* [ ] Improve diagnostics.
* [ ] Add useful metrics.
* [ ] Improve structured logging.
* [ ] Validate configuration early.
* [ ] Add CI.

**Commit after completion.**

Suggested commit:

```text
chore(ops): improve diagnostics testing and observability
```

---

# 20. REQUIRED FINAL VALIDATION

Before declaring this correction plan complete:

## Automated Tests

* [ ] Install project cleanly.
* [ ] Run full test suite.
* [ ] No existing tests removed to make the build pass.
* [ ] New behaviour has new tests.

## Resume Tests

* [ ] Start a download.
* [ ] Interrupt it.
* [ ] Verify partial state.
* [ ] Restart.
* [ ] Verify safe continuation.
* [ ] Verify no duplicate database record.

## Proxy Tests

* [ ] Configured proxy works.
* [ ] Override works.
* [ ] Only one proxy argument exists.
* [ ] Unhealthy proxy follows controlled failure path.

## Pipeline Scope Tests

* [ ] Process one video.
* [ ] Confirm unrelated videos remain unchanged.
* [ ] Run batch processing.
* [ ] Confirm batch mode still works.

## Recovery Tests

* [ ] Simulate crash during download.
* [ ] Simulate crash during conversion.
* [ ] Restart.
* [ ] Confirm correct recovery.
* [ ] Confirm no duplicate audio output.

## Worker Tests

* [ ] Start worker A.
* [ ] Attempt worker B.
* [ ] Confirm worker B does not duplicate work.

## Qwen Tests

* [ ] Qwen remains optional.
* [ ] Pipeline works completely with Qwen disabled.
* [ ] Rules handle obvious Tadabbur titles.
* [ ] Ambiguous items can be measured.

---

# 21. FINAL ARCHITECTURAL PRINCIPLE

The final system should remain simple:

```text
                     SOURCES
                        │
                        ▼
                  yt-dlp DISCOVERY
                        │
                        ▼
                    SQLite
                  Source/Video
                     State
                        │
                        ▼
              RULE-BASED CLASSIFIER
                        │
                  Tadabbur?
                  /        \
                YES        NO
                 │          │
                 ▼          ▼
             DOWNLOAD      IGNORE
                 │
                 ▼
        RESUMABLE yt-dlp DOWNLOAD
                 │
                 ▼
             VALIDATION
                 │
                 ▼
           AUDIO / FFmpeg
                 │
                 ▼
          METADATA + SERIES
                 │
                 ▼
        RULE-BASED TAGGING
                 │
                 ▼
          OPTIONAL QWEN
        ONLY IF AMBIGUOUS
                 │
                 ▼
              CATALOG
                 │
          ┌──────┴──────┐
          ▼             ▼
    Internet Archive   Web App
```

The recovery layer operates across the entire system:

```text
SQLite State
     +
Part Files
     +
Retry State
     +
Persistent Circuit Breaker
     +
Worker Lock
     +
Validation
          │
          ▼
AUTONOMOUS RECOVERY
```

---

# SUCCESS DEFINITION

This correction work is successful when the pipeline can:

1. Discover new videos from configured sources.
2. Identify Tadabbur content deterministically.
3. Store state safely in SQLite.
4. Download media through the configured network path.
5. Resume interrupted downloads.
6. Avoid duplicate downloads.
7. Convert to audio safely.
8. Preserve series/session metadata.
9. Categorize and tag content without requiring an LLM.
10. Recover after crashes or reboots.
11. Avoid overlapping workers.
12. Back off intelligently during repeated transient failures.
13. Preserve cooldown state across restarts.
14. Continue functioning with Qwen completely disabled.
15. Produce a clean catalog ready for Internet Archive and the future web app.

---

# AGENT FINAL RULE

Do not "modernize" this project by replacing its architecture.

The current project already has the important foundations:

* yt-dlp abstraction
* SQLite persistence
* repository pattern
* state machine
* rules-first classification
* metadata/tagging
* series support
* recovery logic
* retry handling
* publishing separation
* test coverage

Improve these foundations incrementally.

The goal is:

> A boring, reliable, autonomous pipeline that can run for months with
> minimal human intervention.

Reliability is more valuable than architectural cleverness.

```

I recommend saving that exactly as `correction.md` at the repository root. The most important instruction for your agent is to **complete Stage 1 fully before touching the rest**—especially the resumable-download fix—because that directly affects the core reason you're building this pipeline around yt-dlp.
```
