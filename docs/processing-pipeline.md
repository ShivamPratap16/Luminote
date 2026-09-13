# AI Lecture Notes Platform — Processing Pipeline

**Version:** 0.1 (V1)

## 1. Core pipeline

```text
YouTube URL
    ↓
Validate + normalize
    ↓
Create lecture/job
    ↓
Queue background job
    ↓
Metadata
    ↓
Media preparation
    ↓
Transcription
    ↓
Chapter detection / normalization
    ↓
Structured notes generation
    ↓
PDF rendering
    ↓
Artifact storage
    ↓
Completed
```

## 2. Stage 0 — validation

Input:

```text
youtube_url
```

Actions:

1. Parse URL.
2. Confirm supported YouTube host/path.
3. Extract video ID.
4. Normalize URL.
5. Reject obviously invalid input.

Output:

```text
normalized_video_id
normalized_url
```

No expensive work occurs before this stage passes.

## 3. Stage 1 — lecture creation

Create:

- lecture record
- processing job

Then enqueue the job.

The API returns immediately.

## 4. Stage 2 — metadata

Retrieve permitted source metadata.

Persist:

- title
- duration
- channel
- thumbnail reference
- description where useful

Update job stage:

```text
METADATA_COMPLETED
```

## 5. Stage 3 — media preparation

Obtain media required for processing using permitted access.

Normalize audio with FFmpeg into a format suitable for transcription.

Prefer a temporary/local worker file for intermediate media and move only required long-lived assets to object storage.

Persist the fact that media preparation succeeded.

## 6. Stage 4 — transcription

Input:

```text
audio
```

Output:

```text
transcript_segments[]
```

Each segment contains:

```text
start_seconds
end_seconds
text
segment_index
```

Store segments transactionally so a failed later stage does not lose the transcript.

## 7. Stage 5 — chapters

Use source chapters when available.

If no source chapters exist, create derived logical sections later. V1 may use a simple transcript-based segmentation strategy.

Store chapter boundaries because they are useful both to the AI prompt and to future UI clients.

## 8. Stage 6 — context assembly

Do not send unrelated database records directly to the model.

Build a controlled context object:

```json
{
  "lecture": {
    "title": "..."
  },
  "chapters": [
    {
      "title": "...",
      "start_seconds": 0,
      "end_seconds": 600
    }
  ],
  "transcript": [
    {
      "start_seconds": 0,
      "end_seconds": 12,
      "text": "..."
    }
  ]
}
```

The context builder is responsible for truncation/chunking when the material is larger than the model context window.

## 9. Stage 7 — structured notes generation

Prompt the AI to return structured JSON following a versioned schema.

Example schema:

```json
{
  "title": "Lecture title",
  "overview": "Short overview",
  "sections": [
    {
      "title": "Section title",
      "summary": "...",
      "key_points": ["..."],
      "examples": ["..."],
      "important_terms": ["..."],
      "timestamps": [123.4]
    }
  ],
  "final_takeaways": ["..."]
}
```

The backend must validate the model response against a schema before storing it.

Never assume an LLM response is valid just because it looks like JSON.

## 10. Stage 8 — notes persistence

Store the validated structured notes in the `notes.content_json` field.

At this point the core learning artifact exists independently of the PDF.

## 11. Stage 9 — PDF generation

Input:

```text
validated structured notes
```

Steps:

1. Render notes using an HTML template.
2. Add styling, headings, tables, page breaks, timestamps, and source information.
3. Render HTML to PDF using Playwright.
4. Validate the produced file exists and is non-empty.
5. Upload PDF to object storage.
6. Create artifact record.

## 12. Stage 10 — completion

Update:

```text
job.status = completed
job.current_stage = completed
job.progress = 100
```

The API can now expose:

- structured notes
- transcript
- PDF artifact

## 13. Stage progress model

Suggested weights:

```text
METADATA             5%
MEDIA_PREPARATION   15%
TRANSCRIPTION       35%
CHAPTERS            45%
NOTE_GENERATION     75%
PDF_GENERATION      95%
COMPLETED          100%
```

These are initial UI progress estimates, not scientific measurements. Replace them with measured durations after observing real jobs.

## 14. V2 multimodal pipeline

Once V1 is reliable:

```text
Video
 ↓
Scene/slide detection
 ↓
Candidate frames
 ↓
OCR
 ↓
Visual classification
 ↓
Transcript + visual context
 ↓
Structured knowledge
 ↓
Notes
```

Do not send every frame to the AI. First reduce the frame set with deterministic processing.

## 15. V3 knowledge pipeline

Eventually:

```text
Transcript chunks
Visual facts
OCR
Chapters
Notes
        ↓
Knowledge model
        ↓
Embeddings / pgvector
        ↓
Search + RAG
```

This enables future lecture Q&A without reprocessing the original media.
