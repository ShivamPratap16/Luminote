from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Lecture Notes Platform"
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/lecture_notes"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # Storage
    STORAGE_BACKEND: str = "local"  # "local" or "s3"
    STORAGE_LOCAL_PATH: str = "./storage"
    STORAGE_BUCKET_NAME: str = "lecture-notes-artifacts"
    STORAGE_S3_ENDPOINT: Optional[str] = None
    STORAGE_S3_ACCESS_KEY: Optional[str] = None
    STORAGE_S3_SECRET_KEY: Optional[str] = None

    # Media / yt-dlp
    MEDIA_TEMP_DIR: str = "./tmp/media"
    MEDIA_MAX_DURATION_SECONDS: int = 14400  # 4 hours

    # Transcription
    WHISPER_MODEL_SIZE: str = "base"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"

    # AI Provider
    AI_PROVIDER: str = "nvidia"  # "nvidia", "openai", or "google"

    # NVIDIA NIM
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_TEXT_MODEL: str = "openai/gpt-oss-20b"
    NVIDIA_VISION_MODEL: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    VISION_MAX_IMAGES_PER_REQUEST: int = 4
    VISION_VIDEO_MAX_HEIGHT: int = 720
    VISION_FRAME_INTERVAL_SECONDS: int = 10
    VISION_MAX_FRAMES: int = 100
    VISION_TEMP_DIR: str = "./tmp/vision"
    VISION_ENABLED: bool = True
    VISION_MAX_ANALYSIS_FRAMES: int = 30
    VISION_MAX_IMAGES_PER_REQUEST: int = 5
    VISION_CONCURRENCY: int = 4
    VISION_TIMEOUT_SECONDS: int = 20
    VISION_MAX_RETRIES: int = 2
    VISION_MIN_FRAME_DISTANCE_SECONDS: int = 30

    # OpenAI (legacy/alternative)
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"

    # Google AI (legacy/alternative)
    GOOGLE_AI_API_KEY: Optional[str] = None
    GOOGLE_AI_MODEL: str = "gemini-1.5-flash"

    AI_REQUEST_TIMEOUT: int = 120
    AI_MAX_RETRIES: int = 3

    # PDF
    PDF_TEMPLATE_DIR: str = os.path.join(os.path.dirname(__file__), "..", "templates")

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = 'ignore'


settings = Settings()



