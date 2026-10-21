import pytest
from unittest.mock import patch, MagicMock
from app.services.youtube_acquisition import YouTubeAcquisitionService, YouTubeAcquisitionBlocked

def test_bot_block_detection():
    service = YouTubeAcquisitionService()
    
    with patch('app.services.youtube_acquisition.yt_dlp.YoutubeDL') as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.side_effect = Exception("ERROR: [youtube] 12345678901: Sign in to confirm you're not a bot. Use --cookies-from-browser")
        
        with pytest.raises(YouTubeAcquisitionBlocked):
            service.get_video_stream('12345678901')

    with patch('app.services.youtube_acquisition.yt_dlp.YoutubeDL') as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.side_effect = Exception("ERROR: Unable to download video data: HTTP Error 404: Not Found")
        
        with pytest.raises(Exception) as excinfo:
            service.get_video_stream('12345678901')
        assert not isinstance(excinfo.value, YouTubeAcquisitionBlocked)
        assert "Failed to extract video info" in str(excinfo.value)
