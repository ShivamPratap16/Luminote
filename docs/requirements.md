# AI Lecture Notes Platform — Requirements

**Version:** 0.1 (V1 backend specification)  
**Status:** Draft for implementation

## 1. Product summary

The system accepts a permitted YouTube lecture URL and converts the lecture into structured, timestamped study notes and a downloadable PDF.

The first implementation is backend-first. The web application and Chrome extension will be clients of the backend and are intentionally deferred until the core processing pipeline is stable.

## 2. Problem

Students often watch long technical lectures but struggle to retain important concepts, examples, formulas, and explanations. Manually taking notes interrupts learning. A useful system should transform a lecture into structured study material while preserving links back to the original lecture.

## 3. Goals for V1

1. Accept a YouTube URL through an API.
2. Validate and normalize the URL.
3. Create a persistent lecture and processing job.
4. Process the lecture asynchronously so API requests do not block.
5. Produce timestamped transcript segments.
6. Generate structured notes from the transcript.
7. Persist the notes as structured data rather than only as Markdown/PDF.
8. Render the structured notes into a PDF.
9. Expose processing status and final artifacts through APIs.
10. Make each processing stage retryable without restarting the entire pipeline.
11. Make duplicate submissions of the same video safe and reusable.
12. Log enough information to diagnose failures and measure performance.

## 4. Explicitly out of scope for V1

- Chrome extension.
- Real-time note generation while watching.
- OCR of slide text.
- Computer-vision understanding of diagrams.
- Multimodal frame analysis.
- Flashcards.
- Quizzes.
- Cross-lecture RAG / semantic search.
- Payments/subscriptions.
- Social/sharing features.
- Mobile application.
- Kubernetes or microservice deployment.
- Multiple production AI providers.

These may be added in later versions without changing the core lecture/job architecture.

## 5. Functional requirements

### FR-01: Create lecture

The API must accept a YouTube URL and create a lecture record plus a processing job.

### FR-02: URL validation

The system must reject malformed or unsupported URLs before creating expensive processing work.

### FR-03: Duplicate detection

A normalized YouTube video ID must uniquely identify a source lecture. Re-submitting an already processed video should reuse the existing lecture or create a new processing attempt against it according to the API contract.

### FR-04: Asynchronous processing

The create-lecture API must return quickly after enqueueing work. Long-running media, transcription, AI, and PDF processing must execute in workers.

### FR-05: Metadata extraction

The pipeline should collect basic source metadata that is useful for notes and UI: video ID, title, channel name where available, duration, thumbnail/description where permitted, and source URL.

### FR-06: Transcript

The system must produce timestamped transcript segments with start time, end time, and text.

### FR-07: Structured notes

The system must generate a structured representation containing at minimum:

- title
- sections
- summaries
- key points
- examples when present
- important timestamps

The AI must not be treated as the database. The structured result must be persisted.

### FR-08: PDF generation

The system must render structured notes into a readable PDF containing headings, paragraphs, lists, and timestamps. PDF generation must be a separate processing step.

### FR-09: Job status

Clients must be able to query processing status, current stage, progress, and failure information.

### FR-10: Artifact access

Clients must be able to retrieve notes and a reference to the generated PDF artifact.

## 6. Non-functional requirements

### NFR-01: Reliability

A worker restart must not lose the source lecture, job state, or already persisted intermediate results.

### NFR-02: Retryability

Transient failures must be retryable. A retry should resume from the failed stage where practical rather than repeating successful expensive work.

### NFR-03: Idempotency

Repeated requests and worker retries must not create uncontrolled duplicate records or duplicate artifacts.

### NFR-04: Observability

Every job should be traceable by job ID and lecture ID. Logs should identify stage, status, duration, and error information.

### NFR-05: Security

Secrets must be stored outside source code. User-controlled input must be validated. Shell commands must not be assembled through unsafe string concatenation.

### NFR-06: Maintainability

The media, transcription, AI, notes, storage, and PDF concerns should be separated into services/modules with clear interfaces.

### NFR-07: Cost awareness

The system should avoid unnecessary AI calls, repeated processing, and sending redundant video frames to multimodal models.

## 7. V1 acceptance criteria

A V1 build is considered successful when a developer can:

1. Submit a valid lecture URL with the API.
2. Receive a lecture ID and job ID immediately.
3. Observe the job move through the expected stages.
4. Obtain a persisted timestamped transcript.
5. Obtain structured notes JSON.
6. Obtain a valid PDF generated from those notes.
7. Restart the worker during processing and recover safely.
8. Retry a failed stage without retranscribing or regenerating everything unnecessarily.
9. Submit the same source video twice without corrupting the data model.
10. Diagnose a failed job from logs and stored job information.

## 8. Later-version requirements

V2 may add OCR and slide/frame analysis.

V3 may add multimodal knowledge construction.

V4 may add embeddings, pgvector, and "Ask my lecture" retrieval.

V5 may add the web dashboard and Chrome extension.
