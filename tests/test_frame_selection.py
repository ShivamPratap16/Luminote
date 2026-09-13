import pytest
from unittest.mock import patch, MagicMock
from app.services.frame_selection import FrameSelectionService
import os

@patch('app.services.youtube_acquisition.YouTubeAcquisitionService.get_video_stream')
@patch('subprocess.run')
def test_frame_selection(mock_run, mock_get_video_stream, tmp_path):
    mock_get_video_stream.return_value = os.path.join(str(tmp_path), "dummy.mp4")

    def side_effect_subprocess(*args, **kwargs):
        cmd = args[0]
        out_pattern = cmd[-1]
        out_dir = os.path.dirname(out_pattern)
        os.makedirs(out_dir, exist_ok=True)
        for i in range(3):
            with open(os.path.join(out_dir, f'frame_{i:05d}.jpg'), 'wb') as f:
                f.write(b'dummy data')

    mock_run.side_effect = side_effect_subprocess

    with patch('PIL.Image.open'), patch('imagehash.phash') as mock_hash:
        mock_hash.side_effect = [100, 150, 150]

        service = FrameSelectionService(temp_dir=str(tmp_path))
        service.min_distance = 5
        candidates, out_dir = service.select_frames('dummy_video_id')

        assert len(candidates) == 2
