import os
import base64
import json
import httpx
import structlog
import asyncio
import time
from typing import List, Dict, Any, Optional
from app.core.config import settings
from app.schemas.vision import VisualEventSchema

logger = structlog.get_logger(__name__)

class VisionService:
    def __init__(self):
        self.api_key = settings.NVIDIA_API_KEY
        self.base_url = settings.NVIDIA_BASE_URL
        self.model = getattr(settings, 'NVIDIA_VISION_MODEL', 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning')
        self.max_retries = getattr(settings, 'VISION_MAX_RETRIES', 2)

    def encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    async def analyze_frames_batch(self, events: List[Dict[str, Any]], transcript_segments: List[Any] = None) -> List[Dict[str, Any]]:
        if not self.api_key:
            logger.warning("NVIDIA_API_KEY not set. Skipping vision analysis.")
            return []

        # Prepare messages
        content = [
            {
                "type": "text", 
                "text": "You are analyzing frames from an educational lecture. Each image corresponds to a frame ID. "
                        "Determine the visual type, important readable text, concepts, and relationships. "
                        "Only report information supported by the image. Do not invent information.\n\n"
                        "Return a JSON array of objects, where each object matches this schema exactly:\n"
                        "{\n"
                        '  "frame_id": "string",\n'
                        '  "event_type": "slide",\n'
                        '  "description": "Shows relationship between X and Y.",\n'
                        '  "visible_text": ["Label 1", "Label 2"],\n'
                        '  "key_information": ["Concept A", "Concept B"]\n'
                        "}\n"
            }
        ]

        for idx, event in enumerate(events):
            base64_image = self.encode_image(event['frame_path'])
            frame_id = f"frame_{idx}"
            event['temp_frame_id'] = frame_id
            
            # Attach context if possible
            ts = event['timestamp']
            ctx = ""
            if transcript_segments:
                nearby = [s.text for s in transcript_segments if ts - 15 <= float(s.start_seconds) <= ts + 15]
                if nearby:
                    ctx = f"\nContext for {frame_id}: " + " ".join(nearby)

            content.append({"type": "text", "text": f"Image ID: {frame_id}{ctx}"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 2048,
            "stream": False
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    
                    content = data['choices'][0]['message']['content']
                    if content.startswith('json'):
                        content = content[7:-3]
                    elif content.startswith(''):
                        content = content[3:-3]
                    
                    parsed_array = json.loads(content)
                    if not isinstance(parsed_array, list):
                        # Attempt to wrap it if it returned a single object incorrectly
                        parsed_array = [parsed_array]
                        
                    results = []
                    for item in parsed_array:
                        fid = item.get('frame_id')
                        # Find matching event
                        matching_event = next((e for e in events if e.get('temp_frame_id') == fid), None)
                        if matching_event:
                            item['timestamp'] = matching_event['timestamp']
                            item['frame_path'] = matching_event['frame_path']
                            item['frame_hash'] = matching_event['frame_hash']
                            results.append(item)
                            
                    return results

            except httpx.HTTPStatusError as e:
                if e.response.status_code in [429, 503, 502, 504] and attempt < self.max_retries:
                    delay = (2 ** attempt) + 1
                    logger.warning("Vision API rate limited/unavailable, retrying", status_code=e.response.status_code, delay=delay)
                    await asyncio.sleep(delay)
                else:
                    logger.error("Vision API HTTP error", status_code=e.response.status_code, error=e.response.text)
                    raise
            except Exception as e:
                if attempt < self.max_retries:
                    delay = (2 ** attempt) + 1
                    logger.warning("Vision analysis failed, retrying", error=str(e), delay=delay)
                    await asyncio.sleep(delay)
                else:
                    logger.error("Vision analysis failed permanently", error=str(e))
                    raise
        
        return []

    # Keeping old sync method for compatibility if needed elsewhere
    def analyze_frame(self, frame_path: str, context: str = "") -> Optional[VisualEventSchema]:
        # Legacy method
        pass
