# AI Lecture Notes Platform — Architecture

**Version:** 0.1 (V1)

## 1. Architectural goal

Build a backend that can process a long lecture asynchronously, persist intermediate results, recover from failures, and expose a clean API to future web and browser-extension clients.

The central design principle is:

> The API starts work; workers perform work; PostgreSQL stores durable state; object storage stores files; every expensive stage produces a reusable result.

## 2. High-level architecture

```text
                    Future Clients
              ┌───────────┴───────────┐
              │                       │
          Web App                 Chrome Extension
              │                       │
              └───────────┬───────────┘
                          │ HTTP/SSE
                          ▼
                  ┌──────────────┐
                  │   FastAPI    │
                  │     API      │
                  └──────┬───────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
       PostgreSQL      Redis       Object Storage
       durable state   queue       PDFs/files
                         │
                         ▼
                    ┌──────────┐
                    │  Worker  │
                    └────┬─────┘
                         │
       ┌─────────────────┼──────────────────┐
       ▼                 ▼                  ▼
    Media/FFmpeg      Whisper              LLM
       │                 │                  │
       └─────────────────┼──────────────────┘
                         ▼
                 Structured Knowledge
                         │
                         ▼
                    PDF Renderer
```

## 3. Components

### 3.1 FastAPI API

Responsibilities:

- request validation
- source URL normalization
- lecture/job creation
- reading lecture and note state
- returning job status
- artifact access
- authentication/authorization later
- lightweight streaming of progress via SSE

Non-responsibilities:

- long-running transcription
- large file processing
- AI generation that can take significant time
- PDF generation

### 3.2 PostgreSQL

The durable system of record for:

- lectures
- processing jobs
- transcript segments
- chapters
- notes
- artifacts
- future frames/analysis records

PostgreSQL must store state needed to recover after a process restart.

### 3.3 Redis

Redis is used as the queue/coordination layer for background work.

V1 should keep Redis responsibilities narrow. It is not the system of record.

### 3.4 Background worker

A worker consumes processing jobs and runs the pipeline stage by stage.

The worker must:

- update job state
- persist intermediate outputs
- retry transient failures
- emit structured logs
- avoid repeating successful stages unnecessarily

### 3.5 Media layer

Use `yt-dlp` only for content the application is permitted to access/process, and FFmpeg for audio/media conversion.

### 3.6 Transcription layer

Use a provider abstraction around faster-whisper or another transcription implementation.

### 3.7 AI layer

Use an AI-provider abstraction instead of scattering provider-specific calls throughout the application.

Conceptual interface:

```python
class AIProvider:
    def generate_notes(self, context): ...
    def generate_structured_knowledge(self, context): ...
```

The implementation may initially use one hosted model provider. A future provider can be substituted without redesigning the rest of the pipeline.

### 3.8 PDF renderer

Convert structured notes to HTML/CSS and render HTML to PDF using Playwright in V1.

The PDF renderer should consume structured notes, not raw transcripts.

### 3.9 Object storage

Store generated PDFs and future large media/image artifacts in S3-compatible object storage such as Cloudflare R2.

PostgreSQL stores metadata and object keys, not large binary blobs.

## 4. Key architectural principles

### 4.1 Durable intermediate state

Prefer:

```text
transcript -> DB
notes -> DB
PDF -> object storage
```

over keeping these only in worker memory.

### 4.2 Stage isolation

Each major processing stage should be independently callable/testable.

```text
metadata
media
transcription
knowledge
notes
pdf
```

### 4.3 One worker job, multiple recoverable stages

A lecture job represents the overall pipeline. Each stage records completion so the system can resume after a failure.

### 4.4 Backend as product core

Web and extension clients must contain minimal business logic. They call the backend APIs.

## 5. Deployment architecture for V1

Start with a small deployment:

```text
Vercel (later: web UI)
        |
        v
FastAPI service
        |
   +----+----+
   |         |
Postgres   Redis
             |
             v
          Worker
```

For local development, use Docker Compose for PostgreSQL and Redis. The worker can run locally as a separate process.

Do not introduce Kubernetes or multiple microservices in V1.

## 6. Scaling path

If load increases:

1. Add more worker processes.
2. Separate CPU-heavy transcription workers from AI/PDF workers if measurement shows different scaling needs.
3. Move media/PDF files to object storage.
4. Add caching/deduplication.
5. Add observability and metrics.
6. Split services only when actual ownership/scaling boundaries justify it.
