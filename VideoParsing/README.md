# VideoParsing - GCP Video Processing Pipeline

Automated pipeline that processes horse racing videos uploaded to a GCS bucket. Videos are segmented by distance markers (1200m, 1000m, 800m, etc.) using Gemini vision, upscaled, slowed down, analyzed by Gemini 2.5 Pro for metadata extraction, and results are stored in BigQuery.

## Architecture

```
GCS Bucket (video upload)
    |  OBJECT_FINALIZE notification
Pub/Sub Topic
    |  Push subscription (authenticated)
Cloud Run Service (Python/Flask)
    |-- Download video from GCS
    |-- Gemini 2.5 Pro: detect distance markers (1000m, 800m, etc.)
    |-- FFmpeg: segment at distance marker timestamps
    |   (fallback: fixed 30s chunks if no markers detected)
    |-- FFmpeg: upscale (lanczos to 1920x1080)
    |-- FFmpeg: slow down (2x via setpts/atempo)
    |-- Upload processed segments to GCS
    |-- Gemini 2.5 Pro: extract metadata per segment
    +-- Write metadata to BigQuery (with distance_marker)
```

## Project Structure

```
VideoParsing/
├── app/
│   ├── main.py              # Flask endpoint, orchestration logic
│   ├── config.py            # Environment-based configuration
│   ├── video_processor.py   # FFmpeg: download, segment, upscale, slow, upload
│   ├── gemini_extractor.py  # Gemini API: distance marker detection + metadata extraction
│   └── bq_writer.py         # BigQuery schema creation and writes
├── deploy/
│   ├── setup.sh             # Create GCS, Pub/Sub, BQ, service account, APIs
│   ├── deploy.sh            # Build container, deploy Cloud Run, create subscription
│   └── teardown.sh          # Cleanup all resources
├── Dockerfile
└── requirements.txt
```

## Prerequisites

- Google Cloud project with billing enabled
- `gcloud` CLI installed and authenticated
- Required APIs: Cloud Run, Pub/Sub, Cloud Storage, BigQuery, Cloud Build, Vertex AI

## Setup & Deployment

### 1. Configure

Edit `PROJECT_ID` and `REGION` in all three deploy scripts:
- `deploy/setup.sh`
- `deploy/deploy.sh`
- `deploy/teardown.sh`

### 2. Create Infrastructure

```bash
bash deploy/setup.sh
```

This creates:
- Service account with required IAM roles
- Input and output GCS buckets
- Pub/Sub topic with GCS notification
- Dead-letter topic for failed messages

### 3. Deploy

```bash
bash deploy/deploy.sh
```

This:
- Builds the container image via Cloud Build
- Deploys to Cloud Run (4Gi memory, 2 CPU, 3600s timeout)
- Creates a Pub/Sub push subscription with OIDC authentication

### 4. Test

Upload a video to the input bucket:

```bash
gcloud storage cp your_video.mp4 gs://<PROJECT_ID>-video-input/
```

Check logs:

```bash
gcloud run services logs read video-pipeline --region=<REGION> --project=<PROJECT_ID>
```

Query results in BigQuery:

```sql
SELECT video_id, segment_index, distance_marker, description
FROM video_metadata.segments
ORDER BY video_id, segment_index
```

## Pipeline Details

### Segmentation Modes

The pipeline supports two segmentation modes controlled by the `SEGMENT_MODE` env var:

**Distance-based (default):** Sends the full video to Gemini to detect distance markers on the track (e.g., 1000m, 800m, 600m). FFmpeg then cuts the video at the detected timestamps using `-ss` and `-to`. Each segment corresponds to the section of the race between two distance markers. Falls back to time-based segmentation if no markers are detected.

**Time-based (fallback):** Splits the video into fixed-duration chunks (default 30s) using FFmpeg's `-f segment -segment_time`.

### FFmpeg Processing

| Step | Command | Details |
|------|---------|---------|
| Segment (distance) | `-ss <start> -to <end> -c copy` | Cuts between distance marker timestamps |
| Segment (time) | `-f segment -segment_time 30` | Fallback: splits into 30s chunks |
| Upscale | `-vf scale=1920:1080:flags=lanczos` | Skipped if already >= target resolution |
| Slow down | `-vf setpts=2.0*PTS -af atempo=0.5` | 2x slowdown with audio pitch correction |

### Gemini Metadata Extraction

Each segment is sent to Gemini 2.5 Pro via Vertex AI, which extracts:

- **description** - concise summary of the video content
- **objects** - notable objects visible in the video
- **scenes** - scene changes with timestamps and descriptions
- **transcript** - spoken words and on-screen text
- **key_moments** - notable moments with timestamps

### BigQuery Schema

| Field | Type | Description |
|-------|------|-------------|
| video_id | STRING | Stem of the uploaded filename |
| segment_index | INTEGER | 0-based segment number |
| gcs_uri | STRING | GCS URI of the processed segment |
| description | STRING | Gemini-generated description |
| objects | STRING (REPEATED) | Detected objects |
| scenes | RECORD (REPEATED) | Scene changes (timestamp, description) |
| transcript | STRING | Transcribed speech and text |
| key_moments | RECORD (REPEATED) | Key moments (timestamp, description) |
| processed_at | TIMESTAMP | Processing timestamp |
| duration_sec | FLOAT | Segment duration in seconds |
| distance_marker | STRING | Distance marker label (e.g., "1000m", "800m") |
| video_start_sec | FLOAT | Segment start time in the original video |
| video_end_sec | FLOAT | Segment end time in the original video |

## Configuration

All settings are configurable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| PROJECT_ID | - | GCP project ID |
| REGION | australia-southeast1 | GCP region for resources |
| INPUT_BUCKET | - | GCS bucket for video uploads |
| OUTPUT_BUCKET | - | GCS bucket for processed segments |
| BQ_DATASET | video_metadata | BigQuery dataset name |
| BQ_TABLE | segments | BigQuery table name |
| GEMINI_MODEL | gemini-2.5-pro | Gemini model for metadata extraction |
| GEMINI_LOCATION | us-central1 | Region for Gemini API calls |
| SEGMENT_MODE | distance | Segmentation mode: "distance" or "time" |
| SEGMENT_DURATION_SEC | 30 | Segment length in seconds (time mode only) |
| UPSCALE_RESOLUTION | 1920:1080 | Target upscale resolution |
| SLOWDOWN_FACTOR | 2.0 | Video slowdown multiplier |

## Error Handling

- **Pub/Sub retries** on non-2xx responses with exponential backoff (ack deadline: 600s)
- **Dead-letter topic** after 5 failed delivery attempts
- **Idempotency check** skips videos already processed in BigQuery
- **Gemini retry wrapper** with exponential backoff for 429/503 errors
- **FFmpeg** checks subprocess return codes and logs stderr on failure
- **/tmp cleanup** in finally block to prevent disk exhaustion

## Teardown

```bash
bash deploy/teardown.sh
```

Removes all resources except GCS buckets (for safety). To delete buckets manually:

```bash
gcloud storage rm -r gs://<PROJECT_ID>-video-input
gcloud storage rm -r gs://<PROJECT_ID>-video-output
```
