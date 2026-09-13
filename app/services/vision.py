import os
import base64
import json
import httpx
import structlog
from app.core.config import settings
from app.schemas.vision import VisualEventSchema
from typing import List, Dict, Any, Optional

logger = structlog.get_logger(__name__)

class VisionService:
    def __init__(self):
        self.api_key = settings.NVIDIA_API_KEY
        self.base_url = settings.NVIDIA_BASE_URL
        self.model = getattr(settings, 'NVIDIA_VISION_MODEL', 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning')

    def encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def analyze_frame(self, frame_path: str, context: str = "") -> Optional[VisualEventSchema]:
        if not self.api_key:
            logger.warning("NVIDIA_API_KEY not set. Skipping vision analysis.")
            return None

        base64_image = self.encode_image(frame_path)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }
        
        prompt = '''You are analyzing a frame from an educational lecture.
Identify meaningful educational information visible in the frame.

Determine:
1. visual type: slide, diagram, formula, code, table, chart, example, or other
2. important readable text
3. important concepts represented visually
4. relationships shown by diagrams/charts
5. formulas or code that matter
6. whether the frame contains useful information that is not obvious from the spoken transcript

Only report information supported by the image.
Do not invent information.

Return structured JSON matching this schema:
{
  "event_type": "slide",
  "description": "Shows the relationship between X and Y.",
  "visible_text": ["Label 1", "Label 2"],
  "key_information": ["Concept A", "Concept B"]
}'''

        if context:
            prompt += f"\n\nTranscript context around this frame:\n{context}"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            "max_tokens": 1024,
            "stream": False
        }
        
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                content = data['choices'][0]['message']['content']
                # Sometimes models wrap JSON in markdown block
                if content.startswith('`json'):
                    content = content[7:-3]
                elif content.startswith('`'):
                    content = content[3:-3]
                
                parsed_json = json.loads(content)
                return VisualEventSchema(**parsed_json)
                
        except httpx.HTTPStatusError as e:
            logger.error("Vision API HTTP error", status_code=e.response.status_code, error=e.response.text)
            raise
        except Exception as e:
            logger.error("Vision analysis failed", error=str(e))
            raise
