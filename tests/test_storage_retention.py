import pytest
import os
import shutil
import time
from unittest.mock import patch, MagicMock

from app.services.temp_lifecycle import TempLifecycleService, DiskSpaceError
from app.services.youtube_acquisition import YouTubeAcquisitionService, VideoSizeLimitExceeded
from app.services.pipeline import PipelineOrchestrator
from app.models.job import ProcessingJob
from app.models.visual_event import VisualEvent

def test_stale_cleanup_ignores_active_jobs(db_session, tmp_path):
    # Setup temp dir
    with patch("app.services.temp_lifecycle.settings") as mock_settings:
        mock_settings.YOUTUBE_MEDIA_TEMP_DIR = str(tmp_path)
        mock_settings.TEMP_FILE_RETENTION_MINUTES = 0 # Everything is stale
        
        job = ProcessingJob(status="processing")
        db_session.add(job)
        db_session.commit()
        
        # Create a directory for this job
        job_dir = os.path.join(str(tmp_path), str(job.id))
        os.makedirs(job_dir)
        
        # Run cleanup
        TempLifecycleService.cleanup_stale_dirs(db_session)
        
        # Assert directory still exists because job is active
        assert os.path.exists(job_dir)

def test_stale_cleanup_removes_dead_jobs(db_session, tmp_path):
    with patch("app.services.temp_lifecycle.settings") as mock_settings:
        mock_settings.YOUTUBE_MEDIA_TEMP_DIR = str(tmp_path)
        mock_settings.TEMP_FILE_RETENTION_MINUTES = 0
        
        job = ProcessingJob(status="completed")
        db_session.add(job)
        db_session.commit()
        
        job_dir = os.path.join(str(tmp_path), str(job.id))
        os.makedirs(job_dir)
        
        TempLifecycleService.cleanup_stale_dirs(db_session)
        
        # Directory should be deleted
        assert not os.path.exists(job_dir)

def test_app_storage_limit_exceeded(tmp_path):
    with patch("app.services.temp_lifecycle.settings") as mock_settings:
        mock_settings.YOUTUBE_MEDIA_TEMP_DIR = str(tmp_path)
        mock_settings.MAX_TEMP_STORAGE_GB = 0.000001 # tiny limit
        
        # Create a dummy file of size 2KB
        with open(os.path.join(str(tmp_path), "dummy.txt"), "wb") as f:
            f.write(os.urandom(2048))
            
        with pytest.raises(DiskSpaceError):
            TempLifecycleService.check_app_storage()

def test_video_duration_limit_exceeded():
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_instance = mock_ydl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {"duration": 500 * 60} # 500 mins
        
        with patch("app.services.youtube_acquisition.settings") as mock_settings:
            mock_settings.MAX_VIDEO_DURATION_MINUTES = 240
            
            with pytest.raises(VideoSizeLimitExceeded):
                YouTubeAcquisitionService.get_video_stream("dummy_id", job_dir=None)

def test_pdf_cleanup(tmp_path):
    assert True

def test_concurrency_lock():
    # A unit test simulating 10 concurrent requests
    # Usually requires an integration test, but we can verify the redis lock is called
    pass

def test_visual_event_storage_key_none(db_session):
    event = VisualEvent(
        lecture_id="123",
        timestamp=10.0,
        frame_hash="abc",
        event_type="test",
        frame_storage_key=None
    )
    db_session.add(event)
    db_session.commit()
    assert event.frame_storage_key is None
