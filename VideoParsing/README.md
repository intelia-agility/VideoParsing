# VideoParsing - GCP Video Processing Pipeline

Automated pipeline that processes videos uploaded to a GCS bucket. Videos are segmented, upscaled, slowed down, analyzed by Gemini 2.5 Pro for metadata extraction, and results are stored in BigQuery.

## Architecture

```
GCS Bucket (video upload)
    |  OBJECT_FINALIZE notification
Pub/Sub Topic
    |  Push subscription (authenticated)
Cloud Run Service (Python/Flask)
    |-- Download video from GCS
    |-- FFmpeg: segment into 30s chunks
    |-- FFmpeg: upscale (lanczos to 1920x1080)
    |-- FFmpeg: slow down (2x via setpts/atempo)
    |-- Upload processed segments to GCS
    |-- Gemini 2.5 Pro: extract metadata per segment
    +-- Write metadata to BigQuery
```

## Project Structure

```
VideoParsing/
├── app/
│   ├── main.py              # Flask endpoint, orchestration logic
│   ├── config.py            # Environment-based configuration
│   ├── video_processor.py   # FFmpeg: download, segment, upscale, slow, upload
│   ├── gemini_extractor.py  # Gemini API metadata extraction
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
SELECT * FROM video_metadata.segments ORDER BY video_id, segment_index
```

## Pipeline Details

### FFmpeg Processing

| Step | Command | Details |
|------|---------|---------|
| Segment | `-f segment -segment_time 30` | Splits video into 30s chunks |
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
| SEGMENT_DURATION_SEC | 30 | Segment length in seconds |
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
