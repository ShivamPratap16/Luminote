import os
import pytest
from unittest.mock import patch, MagicMock
from app.services.frame_selection import FrameSelectionService

@patch('yt_dlp.YoutubeDL')
@patch('subprocess.run')
def test_frame_selection(mock_run, mock_ydl, tmp_path):
    import shutil
    
    # Mock yt-dlp to pretend it downloaded a file
    mock_ydl_instance = MagicMock()
    mock_ydl.return_value.__enter__.return_value = mock_ydl_instance
    mock_ydl_instance.extract_info.return_value = {'height': 720}
    
    # Mock ffmpeg subprocess to create dummy frames
    def side_effect_subprocess(*args, **kwargs):
        # find the out_dir from args
        cmd = args[0]
        out_pattern = cmd[-1]
        out_dir = os.path.dirname(out_pattern)
        os.makedirs(out_dir, exist_ok=True)
        # touch a few dummy frame files
        for i in range(3):
            with open(os.path.join(out_dir, f'frame_{i:05d}.jpg'), 'wb') as f:
                f.write(b'dummy data')
    
    mock_run.side_effect = side_effect_subprocess

    # Mock Image open and imagehash to avoid real processing
    with patch('PIL.Image.open'), patch('imagehash.phash') as mock_hash:
        mock_hash.side_effect = [100, 150, 150]
        
        service = FrameSelectionService(temp_dir=str(tmp_path))
        service.min_distance = 5
        candidates, out_dir = service.select_frames('dummy_video_id')
        
        assert len(candidates) == 2
        assert mock_run.called
        assert mock_ydl_instance.extract_info.called



