import os


class Config:
    PROJECT_ID = os.environ.get("PROJECT_ID", "")
    REGION = os.environ.get("REGION", "australia-southeast1")
    INPUT_BUCKET = os.environ.get("INPUT_BUCKET", "")
    OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "")
    BQ_DATASET = os.environ.get("BQ_DATASET", "video_metadata")
    BQ_TABLE = os.environ.get("BQ_TABLE", "segments")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
    GEMINI_LOCATION = os.environ.get("GEMINI_LOCATION", "us-central1")
    SEGMENT_DURATION_SEC = int(os.environ.get("SEGMENT_DURATION_SEC", "30"))
    UPSCALE_RESOLUTION = os.environ.get("UPSCALE_RESOLUTION", "1920:1080")
    SLOWDOWN_FACTOR = float(os.environ.get("SLOWDOWN_FACTOR", "2.0"))
    SEGMENT_MODE = os.environ.get("SEGMENT_MODE", "distance")  # "distance" or "time"
