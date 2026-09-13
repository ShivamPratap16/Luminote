"""Tests for YouTubeService URL validation and normalization."""
import pytest
from app.services.youtube import YouTubeService, YouTubeValidationError


class TestExtractVideoId:
    """Test video ID extraction from various URL formats."""

    def test_standard_url(self):
        assert YouTubeService.extract_video_id(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_url_with_extra_params(self):
        assert YouTubeService.extract_video_id(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120"
        ) == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert YouTubeService.extract_video_id(
            "https://youtu.be/dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert YouTubeService.extract_video_id(
            "https://www.youtube.com/embed/dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        assert YouTubeService.extract_video_id(
            "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_no_www(self):
        assert YouTubeService.extract_video_id(
            "https://youtube.com/watch?v=dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_http(self):
        assert YouTubeService.extract_video_id(
            "http://www.youtube.com/watch?v=dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_invalid_url_raises(self):
        with pytest.raises(YouTubeValidationError):
            YouTubeService.extract_video_id("https://example.com/video")

    def test_empty_string_raises(self):
        with pytest.raises(YouTubeValidationError):
            YouTubeService.extract_video_id("")

    def test_malformed_video_id_raises(self):
        with pytest.raises(YouTubeValidationError):
            YouTubeService.extract_video_id("https://youtube.com/watch?v=short")

    def test_vimeo_raises(self):
        with pytest.raises(YouTubeValidationError):
            YouTubeService.extract_video_id("https://vimeo.com/123456")


class TestNormalizeUrl:
    def test_normalize(self):
        assert YouTubeService.normalize_url("dQw4w9WgXcQ") == \
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

class TestFetchCaptions:
    @pytest.fixture
    def mock_transcript_api(self, mocker):
        return mocker.patch("youtube_transcript_api.YouTubeTranscriptApi")

    def test_fetch_captions_success(self, mock_transcript_api, mocker):
        mock_transcript_list = mocker.Mock()
        mock_transcript = mocker.Mock()
        mock_transcript.is_generated = False
        mock_transcript.fetch.return_value = [
            {"text": "Hello world", "start": 1.0, "duration": 2.5},
            {"text": " This is a test. ", "start": 3.5, "duration": 1.0},
            {"text": " ", "start": 5.0, "duration": 1.0}  # Should be skipped
        ]
        
        mock_transcript_list.find_manually_created_transcript.return_value = mock_transcript
        mock_transcript_api.return_value.list.return_value = mock_transcript_list
        
        captions = YouTubeService.fetch_captions("test-id")
        
        assert captions is not None
        assert len(captions) == 2
        assert captions[0] == {"start_seconds": 1.0, "end_seconds": 3.5, "text": "Hello world"}
        assert captions[1] == {"start_seconds": 3.5, "end_seconds": 4.5, "text": "This is a test."}

    def test_fetch_captions_unavailable(self, mock_transcript_api):
        from youtube_transcript_api._errors import TranscriptsDisabled
        mock_transcript_api.return_value.list.side_effect = TranscriptsDisabled("test-id")
        
        captions = YouTubeService.fetch_captions("test-id")
        assert captions is None

    def test_fetch_captions_empty_after_normalization(self, mock_transcript_api, mocker):
        mock_transcript_list = mocker.Mock()
        mock_transcript = mocker.Mock()
        mock_transcript.is_generated = False
        mock_transcript.fetch.return_value = [
            {"text": "   ", "start": 1.0, "duration": 2.5},
        ]
        
        mock_transcript_list.find_manually_created_transcript.return_value = mock_transcript
        mock_transcript_api.return_value.list.return_value = mock_transcript_list
        
        captions = YouTubeService.fetch_captions("test-id")
        assert captions is None
