# AI Lecture Notes Platform — Architecture Decision Record

**Version:** 0.1

This document records important choices and why they were made. It is intentionally biased toward a small, understandable system that can grow later.

## ADR-001: Backend-first development

**Decision:** Build the backend and processing pipeline before the web UI and Chrome extension.

**Reason:** The core technical risk is not the form that accepts a URL; it is reliable asynchronous processing of media, transcription, AI generation, and PDF creation. Future clients should consume a stable API.

**Consequence:** The system must have good API contracts and testable backend stages before UI work starts.

## ADR-002: FastAPI for the API

**Decision:** Use Python + FastAPI.

**Reason:** The project has substantial Python-based media/AI/OCR ecosystem requirements. FastAPI provides clean request validation and asynchronous API handling without requiring the API process to perform long-running work.

**Consequence:** Node.js remains available for future tools if useful, but the core processing backend is Python.

## ADR-003: PostgreSQL as the source of truth

**Decision:** Use PostgreSQL rather than MongoDB for the main application database.

**Reason:** Lectures, jobs, transcript segments, chapters, notes, and artifacts have clear relationships and require durable state, constraints, transactions, and indexes.

**Consequence:** Structured note content may still use JSONB where flexibility is valuable.

## ADR-004: Redis + background workers

**Decision:** Use Redis-backed background jobs (e.g. Celery) for media/AI/PDF processing.

**Reason:** Processing can take minutes and should not block API requests. Workers can scale independently and retry failed work.

**Consequence:** The project gains operational complexity, but that complexity directly solves a real problem in this product.

## ADR-005: Stage-based processing

**Decision:** Model processing as explicit stages.

**Reason:** Video processing has many failure points. Persisting stage results allows safe retries and partial recovery.

**Consequence:** Job state needs both an overall status and a current stage.

## ADR-006: Structured notes are the primary learning artifact

**Decision:** Persist structured notes JSON before generating PDF.

**Reason:** PDF is only one presentation format. Structured data can later produce web notes, flashcards, quizzes, exports, and RAG chunks.

**Consequence:** PDF rendering remains replaceable.

## ADR-007: HTML/CSS to PDF

**Decision:** Generate notes as HTML and render them to PDF with Playwright.

**Reason:** HTML/CSS is substantially easier to style for headings, tables, page breaks, images, links, and responsive layouts than manually positioning PDF primitives.

**Consequence:** The service must have a reliable headless-browser rendering environment.

## ADR-008: Object storage for generated files

**Decision:** Store PDFs and future large binary artifacts in S3-compatible object storage.

**Reason:** PostgreSQL should store metadata, not large binary files. Object storage gives independent file lifecycle management.

**Consequence:** The artifact layer must generate secure access URLs or proxy downloads.

## ADR-009: AI provider abstraction

**Decision:** Hide the selected model provider behind an internal service interface.

**Reason:** The model provider is replaceable and external. Business logic should not become tightly coupled to one provider's SDK.

**Consequence:** Slightly more code now, significantly easier provider changes later.

## ADR-010: Start with transcript-only notes

**Decision:** V1 generates notes from transcript/metadata and adds OCR/visual analysis later.

**Reason:** Multimodal processing is valuable but adds significant complexity and cost. V1 should establish the job architecture and end-to-end product first.

**Consequence:** The initial notes will not capture all information shown visually in a lecture.

## ADR-011: No microservices in V1

**Decision:** Use a modular monolith API plus worker processes rather than multiple independent services.

**Reason:** The project does not yet have scale or organizational boundaries that justify microservice overhead.

**Consequence:** Modules must still have clear interfaces so future extraction is possible if real scaling demands it.

## ADR-012: Polling first, SSE later

**Decision:** Start with a normal job-status endpoint. Add SSE after the backend pipeline is stable.

**Reason:** Polling is simpler to debug and sufficient for V1. Real-time progress improves UX but is not core processing functionality.

**Consequence:** The backend should expose job status cleanly so either polling or SSE can consume the same state.

## ADR-013: No Kubernetes initially

**Decision:** Do not use Kubernetes for V1.

**Reason:** It adds operational complexity without solving an existing scale problem. Docker Compose is sufficient locally; simple hosted services are sufficient initially.

**Consequence:** Scaling will initially mean more worker instances/processes rather than cluster orchestration.

## ADR-014: Preserve timestamps everywhere

**Decision:** Treat timestamps as first-class data.

**Reason:** A trustworthy study tool should let users verify a note against the original lecture. Timestamps also support later extension features such as save-moment and current-topic views.

**Consequence:** Transcript and note schemas must retain source timing information.

## ADR-015: Build for permitted content access

**Decision:** The source/download layer must follow the permissions, terms, and access controls applicable to the content being processed.

**Reason:** Technical ability to retrieve content does not itself establish permission to download, store, or redistribute it.

**Consequence:** The product should distinguish processing a user's permitted content from unrestricted downloading/redistribution.

## ADR-016: NVIDIA NIM as default AI provider

**Context:** The initial implementation used OpenAI (GPT-4o) and Google Gemini as AI providers behind an abstract interface. The project needs to use NVIDIA NIM for note generation.

**Decision:** Replace the default AI provider with NVIDIA NIM, accessed through the OpenAI-compatible chat completions API at `https://integrate.api.nvidia.com/v1` with the `openai/gpt-oss-20b` model.

**Alternatives considered:**
- Keep OpenAI as default: rejected because the project requirement specifies NVIDIA NIM.
- Remove OpenAI/Google providers entirely: rejected to preserve provider flexibility per ADR-009.

**Consequences:**
- The `openai` Python SDK is reused since NVIDIA NIM exposes an OpenAI-compatible API. No new SDK dependency.
- `google-generativeai` is no longer a required dependency (commented out in requirements).
- The `AI_PROVIDER` default is now `nvidia`. OpenAI and Google remain available as alternatives.
- JSON extraction logic was hardened to handle `<think>` reasoning blocks and markdown code fences that the Qwen model may emit.
- The existing provider abstraction (`AIProvider` interface), retry system, schema validation, and downstream pipeline are unchanged.
