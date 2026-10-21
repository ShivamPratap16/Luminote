<div align="center">
  <h1>🧠 Lecture Notes AI Backend</h1>
  <p><i>An advanced, asynchronous pipeline for converting long-form video lectures into pristine, structured digital notes using parallel AI processing.</i></p>

  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#optimizations">Key Optimizations</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#getting-started">Getting Started</a>
</div>

---

## ⚡ Overview

The **Lecture Notes AI Backend** automates the tedious process of digesting long-form educational videos. By orchestrating a robust, asynchronous processing pipeline, the system extracts audio, generates transcripts, selects key visual frames, and leverages large language models (LLMs) to synthesize structured, timestamped notes—all automatically exported to PDF.

## ✨ Features

- **End-to-End Automation:** Submit a YouTube URL and get a fully structured, multi-sectioned set of notes complete with overviews, timestamps, and key takeaways.
- **Visual Intelligence:** Automatically extracts and deduplicates video frames (slides, whiteboards), passing them to a Vision AI to extract context and merge it into the final notes.
- **Asynchronous Processing:** Built on Celery and Redis to handle heavy video processing without blocking the API.
- **On-Demand PDF Generation:** Notes are served as JSON to frontends, or rendered into styled PDFs via `weasyprint` on demand.

## 🏗️ Architecture

The backend operates as a multi-stage data pipeline orchestrated by Celery:

1. **Acquisition:** Validates and downloads the optimal audio/video streams via `yt-dlp`.
2. **Transcription:** Transcribes the audio into semantic, timestamped segments.
3. **Fast Notes Generation:** Processes the transcript into structured notes using highly parallelized AI chunking.
4. **Visual Analysis:** Extracts 1fps frames, deduplicates them using SSIM (Structural Similarity), and queries a Vision Model to extract visual data.
5. **Enhanced Notes:** A secondary LLM pass that merges the visual context seamlessly into the text notes.
6. **Cleanup:** Aggressive, background temp-file cleanup ensures the server disk never overflows.

---

## 🚀 Key Optimizations & Engineering

During the development of this project, we implemented several advanced architectural optimizations to achieve production-grade performance and reliability:

### 1. Parallel Semantic Chunking (10x Speedup)
Processing a 2-hour transcript in a single monolithic LLM prompt leads to lost context and extreme latency (~600 seconds). We rebuilt the **Fast Notes** engine to use **Semantic Chunking**:
- The transcript is split into overlapping 15-minute chunks based on natural conversational pauses.
- Chunks are processed concurrently using bounded workers (`FAST_NOTES_MAX_CONCURRENCY`).
- Results are deterministically merged, reducing note generation time to **under 60 seconds** on average.
- Graceful exponential backoff and chunk-level idempotency handle API rate limits seamlessly.

### 2. Provider Routing (Gemini + NVIDIA NIM)
The pipeline utilizes a flexible AI provider abstraction layer, allowing different stages to utilize different models:
- **Fast Notes** are routed to **Google Gemini** (via OpenAI SDK compatibility) for blazing-fast text processing.
- **Enhanced Notes & Vision** are routed to **NVIDIA NIM** (e.g., `nemotron-3-nano-omni-30b-a3b-reasoning`) for deep visual reasoning.

### 3. Strict Storage Lifecycle Redesign
Video processing generates massive temporary files (MP4, WAV, thousands of extracted frames). We engineered a strict boundary between permanent and temporary data:
- **Permanent State (PostgreSQL):** Transcripts, metadata, visual events, and the final canonical Notes JSON.
- **Temporary State (Local Disk):** All media files are stored in job-specific directories.
- **Automated Purging:** Using FastAPI `BackgroundTasks` and Celery periodic beats, unreferenced frames are purged immediately after PDF generation, and stale/failed job directories are swept automatically without touching active jobs.

---

## 🛠️ Tech Stack

- **Framework:** FastAPI (Python 3.10+)
- **Task Queue:** Celery + Redis
- **Database:** PostgreSQL + SQLAlchemy
- **AI Integration:** OpenAI SDK, Google Generative AI (Gemini), NVIDIA NIM
- **Media Processing:** FFmpeg, `yt-dlp`
- **PDF Rendering:** WeasyPrint, Jinja2
- **Testing:** Pytest

---

## 🚦 Getting Started

### Prerequisites
- Python 3.10+
- PostgreSQL
- Redis Server
- FFmpeg installed and in your system PATH

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/lecture-notes-backend.git
   cd lecture-notes-backend
   ```

2. **Set up the virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   Create a `.env` file in the root directory:
   ```env
   PROJECT_NAME="Lecture Notes AI"
   DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/lecture_notes"
   REDIS_URL="redis://localhost:6379/0"
   
   # AI Providers
   FAST_NOTES_PROVIDER="gemini"
   GEMINI_API_KEY="your_gemini_key"
   NVIDIA_API_KEY="your_nvidia_key"
   ```

### Running the Services

You need three terminal windows to run the full stack:

1. **Start the FastAPI Server:**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

2. **Start the Celery Worker:**
   ```bash
   celery -A app.worker.celery_app worker -Q main-queue --loglevel=info
   ```

3. **Ensure Redis & Postgres are running.**

---

## 🧪 Testing

The project maintains a rigorous test suite utilizing `pytest` and extensive mocking for external services (YouTube, LLMs).

```bash
# Run all tests
pytest tests/ -v

# Run specific module
pytest tests/test_notes.py -v
```

---

<div align="center">
  <i>Built with ❤️ by shivam</i>
</div>
