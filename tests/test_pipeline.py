import pytest
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session
from app.services.pipeline import PipelineOrchestrator
from app.models.job import ProcessingJob
from app.models.lecture import Lecture
from app.models.transcript import TranscriptSegment

class TestCaptionExtractionStage:
    @pytest.fixture
    def mock_db(self):
        db = Mock(spec=Session)
        return db

    @pytest.fixture
    def mock_youtube(self):
        return Mock()

    @pytest.fixture
    def mock_media(self):
        return Mock()

    @pytest.fixture
    def mock_transcription(self):
        return Mock()

    @pytest.fixture
    def orchestrator(self, mock_db, mock_youtube, mock_media, mock_transcription):
        return PipelineOrchestrator(
            db=mock_db,
            youtube_service=mock_youtube,
            media_service=mock_media,
            transcription_service=mock_transcription,
            notes_service=Mock(),
            pdf_service=Mock(),
            storage_service=Mock()
        )

    def test_captions_available_skips_media_and_transcription(self, orchestrator, mock_db, mock_youtube, mock_media, mock_transcription, mocker):
        # Setup Job and Lecture
        job = ProcessingJob(id="00000000-0000-0000-0000-000000000000", lecture_id="00000000-0000-0000-0000-000000000001")
        lecture = Lecture(id="00000000-0000-0000-0000-000000000001", youtube_video_id="video123")
        
        # Mock DB queries
        mock_db.query.return_value.filter.return_value.first.side_effect = [job, lecture]
        
        # Test 5: duplicate processing logic - assume no existing segments initially
        mock_db.query.return_value.filter.return_value.count.return_value = 0
        
        # Mock metadata
        mock_meta = Mock()
        mock_meta.title = "Test"
        mock_meta.chapters = []
        mock_youtube.fetch_metadata.return_value = mock_meta
        
        # Test 1 & 4: Captions available and normalized correctly
        mock_youtube.fetch_captions.return_value = [
            {"start_seconds": 0.0, "end_seconds": 2.0, "text": "Normalized caption"}
        ]
        
        # Run pipeline up to notes generation (we mock out notes/pdf to simplify)
        orchestrator._stage_chapters = Mock()
        orchestrator._stage_notes = Mock()
        orchestrator._stage_pdf = Mock()
        
        orchestrator.run("job123")
        
        # Assertions
        mock_youtube.fetch_captions.assert_called_once_with("video123")
        
        # Transcript segments should be created (Test 1)
        mock_db.add_all.assert_called_once()
        saved_segments = mock_db.add_all.call_args[0][0]
        assert len(saved_segments) == 1
        assert saved_segments[0].text == "Normalized caption"
        assert saved_segments[0].start_seconds == 0.0
        
        # Media and Transcription stages MUST be skipped (Test 1)
        mock_media.prepare_audio.assert_not_called()
        mock_transcription.transcribe.assert_not_called()

    def test_captions_unavailable_runs_media_and_transcription(self, orchestrator, mock_db, mock_youtube, mock_media, mock_transcription):
        job = ProcessingJob(id="00000000-0000-0000-0000-000000000000", lecture_id="00000000-0000-0000-0000-000000000001")
        lecture = Lecture(id="00000000-0000-0000-0000-000000000001", youtube_video_id="video123")
        mock_db.query.return_value.filter.return_value.first.side_effect = [job, lecture]
        mock_db.query.return_value.filter.return_value.count.return_value = 0
        
        mock_meta = Mock()
        mock_meta.title = "Test"
        mock_meta.chapters = []
        mock_youtube.fetch_metadata.return_value = mock_meta
        
        # Test 2 & 3: Captions unavailable or invalid (returns None)
        mock_youtube.fetch_captions.return_value = None
        
        mock_media.prepare_audio.return_value = Mock(file_path="test.wav", duration_seconds=10)
        mock_transcription.transcribe.return_value = []
        
        orchestrator._stage_chapters = Mock()
        orchestrator._stage_notes = Mock()
        orchestrator._stage_pdf = Mock()
        
        orchestrator.run("job123")
        
        # Assertions
        mock_youtube.fetch_captions.assert_called_once_with("video123")
        
        # Media and Transcription stages MUST run (Test 2)
        mock_media.prepare_audio.assert_called_once_with("video123")
        mock_transcription.transcribe.assert_called_once_with("test.wav")

    def test_existing_segments_skips_caption_extraction(self, orchestrator, mock_db, mock_youtube):
        job = ProcessingJob(id="00000000-0000-0000-0000-000000000000", lecture_id="00000000-0000-0000-0000-000000000001")
        lecture = Lecture(id="00000000-0000-0000-0000-000000000001", youtube_video_id="video123")
        
        mock_db.query.return_value.filter.return_value.first.side_effect = [job, lecture]
        
        # Test 5: Simulate existing segments
        mock_db.query.return_value.filter.return_value.count.return_value = 10
        
        mock_meta = Mock()
        mock_meta.title = "Test"
        mock_youtube.fetch_metadata.return_value = mock_meta
        
        orchestrator._stage_chapters = Mock()
        orchestrator._stage_notes = Mock()
        orchestrator._stage_pdf = Mock()
        
        orchestrator.run("job123")
        
        # Should NOT attempt to fetch captions from YouTube
        mock_youtube.fetch_captions.assert_not_called()
