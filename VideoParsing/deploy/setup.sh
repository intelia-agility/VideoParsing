#!/usr/bin/env bash
set -euo pipefail

#############################
# CONFIGURATION — EDIT THESE
#############################
PROJECT_ID="rfp-accelerator-agent"
REGION="australia-southeast1"
INPUT_BUCKET="${PROJECT_ID}-video-input"
OUTPUT_BUCKET="${PROJECT_ID}-video-output"
TOPIC_NAME="video-upload-notifications"
SERVICE_ACCOUNT_NAME="video-pipeline-sa"
BQ_DATASET="video_metadata"
DEAD_LETTER_TOPIC="video-upload-dlq"
#############################

SA_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Setting project to ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

echo "==> Enabling required APIs"
gcloud services enable \
  run.googleapis.com \
  pubsub.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  generativelanguage.googleapis.com

echo "==> Creating service account: ${SERVICE_ACCOUNT_NAME}"
gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" \
  --display-name="Video Processing Pipeline SA" \
  2>/dev/null || echo "Service account already exists"

echo "==> Granting roles to service account"
for ROLE in \
  roles/storage.objectAdmin \
  roles/bigquery.dataEditor \
  roles/bigquery.jobUser \
  roles/run.invoker; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --quiet
done

echo "==> Creating input bucket: ${INPUT_BUCKET}"
gcloud storage buckets create "gs://${INPUT_BUCKET}" \
  --location="${REGION}" \
  --uniform-bucket-level-access \
  2>/dev/null || echo "Input bucket already exists"

echo "==> Creating output bucket: ${OUTPUT_BUCKET}"
gcloud storage buckets create "gs://${OUTPUT_BUCKET}" \
  --location="${REGION}" \
  --uniform-bucket-level-access \
  2>/dev/null || echo "Output bucket already exists"

echo "==> Creating Pub/Sub topic: ${TOPIC_NAME}"
gcloud pubsub topics create "${TOPIC_NAME}" \
  2>/dev/null || echo "Topic already exists"

echo "==> Creating dead-letter topic: ${DEAD_LETTER_TOPIC}"
gcloud pubsub topics create "${DEAD_LETTER_TOPIC}" \
  2>/dev/null || echo "Dead-letter topic already exists"

echo "==> Setting up GCS notification on input bucket"
# Check if notification already exists
EXISTING=$(gcloud storage buckets notifications list "gs://${INPUT_BUCKET}" 2>/dev/null | grep "${TOPIC_NAME}" || true)
if [ -z "${EXISTING}" ]; then
  gcloud storage buckets notifications create "gs://${INPUT_BUCKET}" \
    --topic="${TOPIC_NAME}" \
    --event-types=OBJECT_FINALIZE
  echo "Notification created"
else
  echo "Notification already exists"
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo "Input bucket:  gs://${INPUT_BUCKET}"
echo "Output bucket: gs://${OUTPUT_BUCKET}"
echo "Pub/Sub topic: ${TOPIC_NAME}"
echo "Service account: ${SA_EMAIL}"
echo ""
echo "Next: run deploy.sh to build and deploy the Cloud Run service."
