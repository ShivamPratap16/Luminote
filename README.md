# AI Lecture Notes Platform — Backend

Backend-first system that converts YouTube lectures into structured, timestamped study notes and downloadable PDFs.

## Prerequisites

You need these installed on your machine:

| Tool | Purpose | Install |
|------|---------|---------|
| **Python 3.11+** | Runtime | [python.org](https://python.org) |
| **Docker Desktop** | PostgreSQL + Redis | [docker.com](https://docs.docker.com/desktop/) |
| **FFmpeg** | Audio conversion | `winget install FFmpeg` or [ffmpeg.org](https://ffmpeg.org/download.html) |

## Quick Setup

### 1. Start infrastructure (PostgreSQL + Redis)

```bash
docker compose up -d
```

### 2. Create virtual environment and install dependencies

```bash
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
```

### 3. Install Playwright browser (for PDF generation)

```bash
playwright install chromium
```

### 4. Configure environment

```bash
copy .env.example .env
```

Edit `.env` and set your **NVIDIA NIM API key**:

```
NVIDIA_API_KEY=nvapi-your-actual-key
```

### 5. Run database migrations

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

### 6. Start the API server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Start the Celery worker (separate terminal)

```bash
venv\Scripts\activate
celery -A app.worker.celery_app worker --loglevel=info --pool=solo
```

> Use `--pool=solo` on Windows. On Linux/macOS you can use `--pool=prefork`.

## Test it

### Create a lecture

```bash
curl -X POST http://localhost:8000/api/v1/lectures ^
  -H "Content-Type: application/json" ^
  -d "{\"youtube_url\": \"https://www.youtube.com/watch?v=VIDEO_ID\"}"
```

### Check job status

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}
```

### Get results

```bash
curl http://localhost:8000/api/v1/lectures/{lecture_id}/transcript
curl http://localhost:8000/api/v1/lectures/{lecture_id}/notes
curl http://localhost:8000/api/v1/lectures/{lecture_id}/artifacts/pdf
```

### Health check

```bash
curl http://localhost:8000/api/v1/health
```

### Run tests

```bash
pytest tests/ -v
```

## API Docs

Once the server is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project Structure

```
app/
├── api/v1/endpoints/    # HTTP endpoints (thin handlers)
├── core/                # Config, logging
├── db/                  # SQLAlchemy session, base
├── models/              # ORM models (Lecture, Job, Transcript, etc.)
├── schemas/             # Pydantic request/response schemas
├── services/            # Business logic
│   ├── youtube.py       # URL validation + metadata
│   ├── media.py         # Audio download + FFmpeg
│   ├── transcription.py # Whisper transcription
│   ├── ai_provider.py   # NVIDIA NIM (primary) / OpenAI / Google AI abstraction
│   ├── notes.py         # Context assembly + note generation
│   ├── pdf.py           # HTML → PDF via Playwright
│   ├── storage.py       # File storage abstraction
│   └── pipeline.py      # Processing orchestrator
├── templates/           # Jinja2 HTML templates
└── worker/              # Celery tasks
```
