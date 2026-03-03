import json
import logging
import os
import subprocess
from pathlib import Path

from google.cloud import storage

from app.config import Config

logger = logging.getLogger(__name__)

storage_client = storage.Client()


def download_video(bucket_name: str, blob_name: str, dest_path: str) -> None:
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(dest_path)
    logger.info("Downloaded gs://%s/%s to %s", bucket_name, blob_name, dest_path)


def upload_file(bucket_name: str, blob_name: str, source_path: str) -> str:
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(source_path)
    uri = f"gs://{bucket_name}/{blob_name}"
    logger.info("Uploaded %s to %s", source_path, uri)
    return uri


def _run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-y"] + args
    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("FFmpeg stderr: %s", result.stderr)
        raise RuntimeError(f"FFmpeg failed (rc={result.returncode}): {result.stderr[-500:]}")


def _get_resolution(video_path: str) -> tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-500:]}")
    info = json.loads(result.stdout)
    stream = info["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _get_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-500:]}")
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def segment_video(input_path: str, output_dir: str) -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    pattern = os.path.join(output_dir, "segment_%04d.mp4")
    _run_ffmpeg([
        "-i", input_path,
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(Config.SEGMENT_DURATION_SEC),
        "-reset_timestamps", "1",
        pattern,
    ])
    segments = sorted(Path(output_dir).glob("segment_*.mp4"))
    logger.info("Created %d segments", len(segments))
    return [str(s) for s in segments]


def upscale_video(input_path: str, output_path: str) -> str:
    target_w, target_h = (int(x) for x in Config.UPSCALE_RESOLUTION.split(":"))
    current_w, current_h = _get_resolution(input_path)
    if current_w >= target_w and current_h >= target_h:
        logger.info("Already at or above target resolution (%dx%d), skipping upscale", current_w, current_h)
        return input_path
    _run_ffmpeg([
        "-i", input_path,
        "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
        "-c:v", "libx264", "-crf", "18",
        "-c:a", "copy",
        output_path,
    ])
    return output_path


def slow_down_video(input_path: str, output_path: str) -> str:
    factor = Config.SLOWDOWN_FACTOR
    if factor == 1.0:
        logger.info("Slowdown factor is 1.0, skipping")
        return input_path
    _run_ffmpeg([
        "-i", input_path,
        "-vf", f"setpts={factor}*PTS",
        "-af", f"atempo={1.0 / factor}",
        "-c:v", "libx264", "-crf", "18",
        output_path,
    ])
    return output_path


def process_segment(segment_path: str, work_dir: str, index: int) -> str:
    base = Path(segment_path).stem
    upscaled = os.path.join(work_dir, f"{base}_upscaled.mp4")
    upscaled = upscale_video(segment_path, upscaled)

    slowed = os.path.join(work_dir, f"{base}_slowed.mp4")
    slowed = slow_down_video(upscaled, slowed)

    return slowed


def get_duration(video_path: str) -> float:
    return _get_duration(video_path)
