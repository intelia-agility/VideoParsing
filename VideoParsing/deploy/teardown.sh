#!/usr/bin/env bash
set -euo pipefail

#############################
# CONFIGURATION — EDIT THESE
#############################
PROJECT_ID="rfp-accelerator-agent"
REGION="australia-southeast1"
SERVICE_NAME="video-pipeline"
TOPIC_NAME="video-upload-notifications"
SUBSCRIPTION_NAME="video-pipeline-push-sub"
DEAD_LETTER_TOPIC="video-upload-dlq"
SERVICE_ACCOUNT_NAME="video-pipeline-sa"
BQ_DATASET="video_metadata"
BQ_TABLE="segments"
#############################

echo "==> Deleting Pub/Sub subscription: ${SUBSCRIPTION_NAME}"
gcloud pubsub subscriptions delete "${SUBSCRIPTION_NAME}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || echo "Subscription not found"

echo "==> Deleting Pub/Sub topic: ${TOPIC_NAME}"
gcloud pubsub topics delete "${TOPIC_NAME}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || echo "Topic not found"

echo "==> Deleting dead-letter topic: ${DEAD_LETTER_TOPIC}"
gcloud pubsub topics delete "${DEAD_LETTER_TOPIC}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || echo "Dead-letter topic not found"

echo "==> Deleting Cloud Run service: ${SERVICE_NAME}"
gcloud run services delete "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || echo "Service not found"

echo "==> Deleting BigQuery table: ${BQ_DATASET}.${BQ_TABLE}"
bq rm -f -t "${PROJECT_ID}:${BQ_DATASET}.${BQ_TABLE}" 2>/dev/null || echo "Table not found"

echo "==> Deleting BigQuery dataset: ${BQ_DATASET}"
bq rm -f -d "${PROJECT_ID}:${BQ_DATASET}" 2>/dev/null || echo "Dataset not found"

echo "==> Deleting service account: ${SERVICE_ACCOUNT_NAME}"
gcloud iam service-accounts delete \
  "${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || echo "Service account not found"

echo ""
echo "=========================================="
echo "Teardown complete!"
echo "=========================================="
echo "NOTE: GCS buckets were NOT deleted for safety."
echo "To delete them manually:"
echo "  gcloud storage rm -r gs://${PROJECT_ID}-video-input"
echo "  gcloud storage rm -r gs://${PROJECT_ID}-video-output"
