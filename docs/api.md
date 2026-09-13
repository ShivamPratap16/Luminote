# AI Lecture Notes Platform — API Contract

**Version:** v1
**Base path:** `/api/v1`

## 1. API principles

- JSON request/response bodies by default.
- Stable machine-readable error codes.
- UUIDs for resource IDs.
- Long-running work is always asynchronous.
- API never returns a multi-minute request waiting for media/AI processing.

## 2. Create lecture

### Request

```http
POST /api/v1/lectures
Content-Type: application/json
```

```json
{
  "youtube_url": "https://www.youtube.com/watch?v=VIDEO_ID"
}
```

### Success response

```http
201 Created
```

```json
{
  "lecture_id": "uuid",
  "job_id": "uuid",
  "status": "queued"
}
```

## 3. Get lecture

```http
GET /api/v1/lectures/{lecture_id}
```

Example:

```json
{
  "id": "uuid",
  "youtube_video_id": "abc123",
  "title": "Operating Systems Lecture",
  "duration_seconds": 3600,
  "status": "processing",
  "created_at": "2026-09-13T10:00:00Z"
}
```

## 4. List lectures

```http
GET /api/v1/lectures?page=1&page_size=20
```

Return paginated results.

## 5. Get job status

```http
GET /api/v1/jobs/{job_id}
```

Example:

```json
{
  "id": "uuid",
  "lecture_id": "uuid",
  "status": "processing",
  "current_stage": "transcription",
  "progress": 38,
  "attempt": 1,
  "error": null
}
```

## 6. Get transcript

```http
GET /api/v1/lectures/{lecture_id}/transcript
```

Example:

```json
{
  "lecture_id": "uuid",
  "segments": [
    {
      "start_seconds": 12.4,
      "end_seconds": 18.9,
      "text": "Virtual memory allows..."
    }
  ]
}
```

## 7. Get chapters

```http
GET /api/v1/lectures/{lecture_id}/chapters
```

## 8. Get structured notes

```http
GET /api/v1/lectures/{lecture_id}/notes
```

Example:

```json
{
  "lecture_id": "uuid",
  "version": 1,
  "schema_version": "1.0",
  "content": {
    "title": "Virtual Memory",
    "sections": [
      {
        "title": "Definition",
        "summary": "...",
        "key_points": ["..."],
        "examples": ["..."],
        "timestamps": [743.2]
      }
    ]
  }
}
```

## 9. Get PDF artifact metadata

```http
GET /api/v1/lectures/{lecture_id}/artifacts/pdf
```

Response:

```json
{
  "artifact_id": "uuid",
  "type": "pdf",
  "mime_type": "application/pdf",
  "download_url": "signed-or-proxied-url",
  "created_at": "2026-09-13T11:00:00Z"
}
```

## 10. Progress streaming

V1 may use polling. After that is stable, provide SSE:

```http
GET /api/v1/jobs/{job_id}/events
Accept: text/event-stream
```

Example events:

```text
event: progress
data: {"stage":"transcription","progress":38}

```

## 11. Error format

Use a consistent structure:

```json
{
  "error": {
    "code": "INVALID_YOUTUBE_URL",
    "message": "The supplied URL is not a supported YouTube URL.",
    "request_id": "uuid"
  }
}
```

Potential codes:

```text
INVALID_YOUTUBE_URL
LECTURE_NOT_FOUND
JOB_NOT_FOUND
LECTURE_ALREADY_PROCESSING
SOURCE_UNAVAILABLE
TRANSCRIPTION_FAILED
AI_GENERATION_FAILED
PDF_GENERATION_FAILED
RATE_LIMITED
INTERNAL_ERROR
```

## 12. API versioning

All public routes start with `/api/v1`.

Breaking changes should create `/api/v2` rather than silently changing V1 behavior.

## 13. Future endpoints

Only add these when their features actually exist:

```text
POST /api/v1/lectures/{id}/ask
POST /api/v1/lectures/{id}/regenerate-notes
POST /api/v1/lectures/{id}/flashcards
POST /api/v1/lectures/{id}/quiz
POST /api/v1/lectures/{id}/moments
```
