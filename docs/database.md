# AI Lecture Notes Platform — Database Design

**Version:** 0.1 (V1)
**Database:** PostgreSQL

## 1. Design principles

- PostgreSQL is the durable source of truth.
- Use UUIDs for internal IDs unless there is a strong reason not to.
- Store timestamps and durations consistently; prefer UTC for persisted timestamps.
- Do not store large PDFs/audio/video blobs in PostgreSQL.
- Preserve source timestamps because they are part of the product's trust model.
- Use JSONB where the schema is expected to evolve rapidly, but keep important queryable fields relational.

## 2. Core tables

## 2.1 lectures

Represents a source lecture/video.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| youtube_video_id | varchar | Indexed; canonical source identifier |
| youtube_url | text | Normalized source URL |
| title | text | Source title |
| channel_name | text nullable | Source channel if available |
| duration_seconds | integer nullable | Source duration |
| thumbnail_url | text nullable | Reference only |
| description | text nullable | Optional source metadata |
| status | varchar | Overall lecture status |
| created_at | timestamptz | Creation time |
| updated_at | timestamptz | Last update |

Recommended unique constraint:

```text
youtube_video_id
```

This allows source-level deduplication.

## 2.2 processing_jobs

Represents an attempt to process a lecture.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| lecture_id | uuid | FK -> lectures.id |
| status | varchar | queued/processing/completed/failed/cancelled |
| current_stage | varchar | Active pipeline stage |
| progress | numeric | 0–100 |
| attempt | integer | Retry count |
| error_code | varchar nullable | Stable machine-readable error |
| error_message | text nullable | Diagnostic message |
| created_at | timestamptz | Queue creation |
| started_at | timestamptz nullable | Worker start |
| completed_at | timestamptz nullable | Completion |
| updated_at | timestamptz | Last state change |

Indexes:

```text
(lecture_id)
(status)
(created_at)
```

## 2.3 transcript_segments

Stores timestamped speech segments.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| lecture_id | uuid | FK |
| segment_index | integer | Stable ordering |
| start_seconds | numeric | Start timestamp |
| end_seconds | numeric | End timestamp |
| text | text | Transcript text |
| created_at | timestamptz | Creation time |

Unique constraint suggestion:

```text
(lecture_id, segment_index)
```

Index:

```text
(lecture_id, start_seconds)
```

## 2.4 lecture_chapters

Stores chapter/section boundaries.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| lecture_id | uuid | FK |
| chapter_index | integer | Ordering |
| title | text | Chapter title |
| start_seconds | numeric | Beginning |
| end_seconds | numeric | End |
| source | varchar | youtube/derived |

Unique constraint:

```text
(lecture_id, chapter_index)
```

## 2.5 notes

Stores structured notes produced from a lecture.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| lecture_id | uuid | FK |
| version | integer | Notes version |
| schema_version | varchar | JSON schema version |
| content_json | jsonb | Structured notes |
| created_at | timestamptz | Creation time |
| updated_at | timestamptz | Last update |

Unique constraint:

```text
(lecture_id, version)
```

## 2.6 artifacts

Represents generated files.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| lecture_id | uuid | FK |
| note_id | uuid nullable | FK -> notes.id |
| type | varchar | pdf/html/json/... |
| storage_key | text | Object-storage key |
| mime_type | varchar | e.g. application/pdf |
| size_bytes | bigint nullable | File size |
| checksum | varchar nullable | Integrity/deduplication |
| created_at | timestamptz | Creation time |

Unique constraint suggestion:

```text
(lecture_id, note_id, type)
```

depending on whether multiple versions are required.

## 3. Later tables

Do not create these until the feature is implemented:

### lecture_frames

```text
id
lecture_id
timestamp_seconds
storage_key
frame_type
created_at
```

### frame_analysis

```text
id
frame_id
ocr_text
visual_description
analysis_json
created_at
```

### embeddings/chunks

For pgvector/RAG later:

```text
id
lecture_id
source_type
source_id
chunk_text
embedding
metadata_json
```

## 4. Relationships

```text
lectures
  ├──< processing_jobs
  ├──< transcript_segments
  ├──< lecture_chapters
  ├──< notes
  │      └──< artifacts
  └──< artifacts
```

## 5. Deletion strategy

For V1, prefer soft logical deletion or explicit lifecycle states for records that may be referenced by generated artifacts.

Physical deletion of stored media should be separated from deleting relational metadata.

## 6. Migration strategy

Use Alembic.

Do not edit production schemas manually.

Every schema change should be represented as a migration that can be applied consistently in every environment.

## Artifacts
PDFs are no longer stored permanently as artifacts. They are generated on demand from Notes JSON and streamed to the client.
