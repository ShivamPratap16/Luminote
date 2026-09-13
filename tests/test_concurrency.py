import pytest
import asyncio
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.job import ProcessingJob
from app.models.lecture import Lecture
from app.main import app
from app.core.config import settings
from httpx import AsyncClient, ASGITransport
import uuid

engine = create_engine(settings.DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
async def test_concurrent_duplicate_requests():
    db = TestingSessionLocal()
    video_id = "c" + uuid.uuid4().hex[:10]
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tasks = [client.post("/api/v1/lectures", json={"youtube_url": url}) for _ in range(10)]
        responses = await asyncio.gather(*tasks)
        
        for r in responses:
            assert r.status_code == 201 or r.status_code == 200, r.text
            
        job_ids = [r.json()["job_id"] for r in responses]
        
        assert len(set(job_ids)) == 1, f"Expected exactly 1 unique job ID, got {len(set(job_ids))}!"
        
        jobs = db.query(ProcessingJob).join(Lecture).filter(Lecture.youtube_video_id == video_id).all()
        assert len(jobs) == 1, f"Expected exactly 1 ProcessingJob in DB, got {len(jobs)}"
        
    db.close()

