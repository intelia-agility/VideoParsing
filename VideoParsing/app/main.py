import base64
import json
import logging
import os
import shutil
import uuid
from pathlib import Path

from flask import Flask, request

from app.bq_writer import ensure_table_exists, is_video_processed, write_segment_metadata
from app.config import Config
from app.gemini_extractor import detect_distance_markers, extract_metadata
from app.video_processor import (
    download_video,
    get_duration,
    process_segment,
    segment_video,
    segment_video_by_timestamps,
    upload_file,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/", methods=["POST"])
def handle_pubsub():
    envelope = request.get_json(silent=True)
    if not envelope or "message" not in envelope:
        logger.warning("Invalid Pub/Sub envelope")
        return "Bad Request: missing message", 400

    message = envelope["message"]
    data = json.loads(base64.b64decode(message.get("data", "")).decode("utf-8"))

    event_type = data.get("eventType") or message.get("attributes", {}).get("eventType", "")
    if event_type and event_type != "OBJECT_FINALIZE":
        logger.info("Skipping event type: %s", event_type)
        return "Ignored", 200

    bucket_name = data.get("bucket", "")
    object_name = data.get("name", "")

    if not bucket_name or not object_name:
        logger.warning("Missing bucket or object name in message")
        return "Bad Request: missing bucket/object", 400

    # Skip files in the output prefix (avoid reprocessing our own output)
    if object_name.startswith("processed/"):
        logger.info("Skipping output prefix file: %s", object_name)
        return "Ignored", 200

    video_id = Path(object_name).stem
    logger.info("Processing video: %s from bucket: %s (video_id: %s)", object_name, bucket_name, video_id)

    # Idempotency check
    if is_video_processed(video_id):
        logger.info("Video %s already processed, skipping", video_id)
        return "Already processed", 200

    job_id = uuid.uuid4().hex[:8]
    work_dir = os.path.join("/tmp", f"video_job_{job_id}")

    try:
        os.makedirs(work_dir, exist_ok=True)

        ensure_table_exists()

        # Download
        input_path = os.path.join(work_dir, "input.mp4")
        download_video(bucket_name, object_name, input_path)

        # Segment
        segments_dir = os.path.join(work_dir, "segments")
        input_gcs_uri = f"gs://{bucket_name}/{object_name}"

        if Config.SEGMENT_MODE == "distance":
            # Pass 1: Detect distance markers via Gemini
            markers = detect_distance_markers(input_path, gcs_uri=input_gcs_uri)
            if markers:
                segment_results = segment_video_by_timestamps(input_path, segments_dir, markers)
            else:
                logger.warning("No distance markers detected, falling back to time-based segmentation")
                segment_paths = segment_video(input_path, segments_dir)
                segment_results = [(p, None) for p in segment_paths]
        else:
            # Fallback: time-based segmentation
            segment_paths = segment_video(input_path, segments_dir)
            segment_results = [(p, None) for p in segment_paths]

        if not segment_results:
            logger.warning("No segments created for %s", object_name)
            return "No segments", 200

        # Process each segment: upscale + slow down + upload + gemini + bigquery
        for idx, (seg_path, distance_marker) in enumerate(segment_results):
            logger.info("Processing segment %d/%d: %s (marker: %s)", idx + 1, len(segment_results), seg_path, distance_marker)

            processed_path = process_segment(seg_path, work_dir, idx)

            # Upload processed segment to output bucket
            output_blob = f"processed/{video_id}/segment_{idx:04d}.mp4"
            gcs_uri = upload_file(Config.OUTPUT_BUCKET, output_blob, processed_path)

            # Extract metadata with Gemini (pass GCS URI for Vertex AI)
            metadata = extract_metadata(processed_path, gcs_uri=gcs_uri)

            # Get duration
            duration = get_duration(processed_path)

            # Write to BigQuery
            write_segment_metadata(video_id, idx, gcs_uri, metadata, duration, distance_marker=distance_marker)

        logger.info("Successfully processed all %d segments for %s", len(segment_results), video_id)
        return "OK", 200

    except Exception:
        logger.exception("Failed to process video %s", object_name)
        return "Internal Server Error", 500

    finally:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.info("Cleaned up %s", work_dir)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
