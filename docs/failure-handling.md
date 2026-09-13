# AI Lecture Notes Platform — Failure Handling

**Version:** 0.1 (V1)

## 1. Failure philosophy

Failures are normal in a media/AI pipeline. The system should assume:

- external sources can disappear or throttle
- transcription can fail
- AI requests can timeout or return invalid output
- PDF rendering can crash
- workers can restart
- network connections can fail

The system must preserve completed work and retry only what needs retrying.

## 2. Failure categories

### A. User/input errors

Examples:

- invalid URL
- unsupported URL
- malformed request

Action:

- fail immediately
- do not enqueue expensive work
- return a clear 4xx error

### B. Source errors

Examples:

- video unavailable
- permissions/access restrictions
- deleted/private content
- temporary source failure

Action:

- classify permanent vs transient
- retry only transient errors
- expose a stable error code

### C. Infrastructure errors

Examples:

- Redis unavailable
- database timeout
- object-storage failure
- worker crash

Action:

- retry transient operations
- use transactions for database state changes
- rely on queue redelivery where appropriate

### D. AI errors

Examples:

- timeout
- rate limit
- invalid JSON
- provider outage
- context too large

Action:

- retry transient failures with backoff
- validate output
- shrink/chunk context when needed
- never persist invalid structured notes as if successful

### E. PDF errors

Examples:

- template error
- browser/render process crash
- missing asset
- output file invalid

Action:

- fail only the PDF stage
- preserve transcript and notes
- allow PDF regeneration

## 3. Retry policy

Use bounded exponential backoff for transient failures.

Example initial policy:

```text
attempt 1 → immediate/short delay
attempt 2 → ~5 sec
attempt 3 → ~30 sec
attempt 4 → ~2 min
```

Exact values should be configurable.

Do not retry permanent validation/content errors endlessly.

## 4. Job state machine

```text
QUEUED
  ↓
PROCESSING
  ↓
  ├── FAILED_TRANSIENT ──→ retry → PROCESSING
  │
  ├── FAILED_PERMANENT
  │
  └── COMPLETED
```

The `current_stage` identifies where the failure happened.

## 5. Stage-level recovery

Example:

```text
Metadata        ✓
Media           ✓
Transcription   ✓
Chapters        ✓
Notes           ✓
PDF             ✗
```

A retry should start at PDF generation, not download/transcribe again.

This requires the worker to check persisted stage outputs before recomputing them.

## 6. Idempotency

Repeated execution of a stage must be safe.

Examples:

- `youtube_video_id` prevents accidental lecture duplication.
- transcript segment uniqueness prevents duplicate segments.
- notes versions prevent uncontrolled overwrites.
- artifact keys/versioning prevent uncontrolled duplicate PDFs.

## 7. Transaction boundaries

Use small, meaningful transactions.

For example:

1. process transcript in memory/local worker files
2. persist all transcript segments in a transaction
3. mark transcription stage completed

Do not hold one giant database transaction open for the entire 30-minute processing job.

## 8. Timeouts

Every external call should have a timeout.

Examples:

- metadata request
- AI request
- object-storage upload
- PDF rendering subprocess

A timeout should result in a controlled failure, not an indefinitely hanging worker.

## 9. Rate limiting and abuse

Before public deployment:

- rate-limit lecture creation
- limit concurrent processing per user
- limit maximum accepted duration
- prevent obvious job-spam patterns

AI/media processing can be expensive, so rate limiting is a cost-control mechanism as well as a security measure.

## 10. Worker crash recovery

A worker may die after doing work but before updating the database.

Use:

- durable job state
- task acknowledgements appropriate to the queue implementation
- stage-level idempotency
- periodic detection of jobs stuck in `processing`

A future watchdog can identify jobs that have been processing longer than a configured threshold and requeue them safely.

## 11. Logging

Every log event should include at least:

```text
request_id / job_id
lecture_id
stage
status
elapsed_time when available
error_code when failed
```

Avoid logging secrets, credentials, signed URLs, or unnecessary personal data.

## 12. User-facing errors

Do not expose raw stack traces.

Instead:

```json
{
  "error": {
    "code": "TRANSCRIPTION_FAILED",
    "message": "We could not transcribe this lecture. The job can be retried."
  }
}
```

Detailed stack traces belong in internal logs.

## 13. Partial results

Partial results should remain usable.

For example:

```text
Transcript ✓
Notes ✓
PDF ✗
```

The user should still be able to access transcript/notes while the PDF is retried.

## 14. Data cleanup

Temporary audio/video files should have lifecycle rules.

Do not keep every large intermediate file forever without a product reason.

Keep durable artifacts that are needed by the product; expire temporary processing files.
