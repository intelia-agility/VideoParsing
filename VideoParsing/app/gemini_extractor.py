import json
import logging
import os
import time

from google import genai
from google.genai import types

from app.config import Config

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Analyze this video segment and extract structured metadata.
Return a JSON object with these fields:
- "description": A concise description of the video content (1-3 sentences).
- "objects": A list of notable objects visible in the video (strings).
- "scenes": A list of scene changes, each with:
    - "timestamp": approximate time in seconds
    - "description": what happens in the scene
- "transcript": Any spoken words or text visible on screen. Empty string if none.
- "key_moments": A list of notable moments, each with:
    - "timestamp": approximate time in seconds
    - "description": why this moment is notable

Return ONLY valid JSON, no markdown fences."""

def _create_client() -> genai.Client:
    return genai.Client(
        vertexai=True,
        project=Config.PROJECT_ID,
        location=Config.GEMINI_LOCATION,
    )


def _extract_with_retry(client: genai.Client, video_path: str, gcs_uri: str | None = None, max_retries: int = 3) -> dict:
    if gcs_uri:
        logger.info("Using GCS URI for Gemini: %s", gcs_uri)
        video_part = types.Part.from_uri(file_uri=gcs_uri, mime_type="video/mp4")
    else:
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        video_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=Config.GEMINI_MODEL,
                contents=[video_part, EXTRACTION_PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            error_str = str(e)
            is_retryable = "429" in error_str or "503" in error_str or "RESOURCE_EXHAUSTED" in error_str
            if is_retryable and attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("Retryable error (attempt %d/%d), waiting %ds: %s", attempt, max_retries, wait, e)
                time.sleep(wait)
            else:
                raise


def extract_metadata(video_path: str, gcs_uri: str | None = None) -> dict:
    client = _create_client()
    metadata = _extract_with_retry(client, video_path, gcs_uri=gcs_uri)
    logger.info("Extracted metadata for %s: %s", video_path, list(metadata.keys()))
    return metadata
