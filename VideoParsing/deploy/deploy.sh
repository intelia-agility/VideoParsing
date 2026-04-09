#!/usr/bin/env bash
set -euo pipefail

#############################
# CONFIGURATION — EDIT THESE
#############################
PROJECT_ID="ramv-sandpit"
REGION="australia-southeast1"
INPUT_BUCKET="${PROJECT_ID}-video-input"
OUTPUT_BUCKET="${PROJECT_ID}-video-output"
SERVICE_NAME="video-pipeline"
SERVICE_ACCOUNT_NAME="video-pipeline-sa"
TOPIC_NAME="video-upload-notifications"
SUBSCRIPTION_NAME="video-pipeline-push-sub"
DEAD_LETTER_TOPIC="video-upload-dlq"
BQ_DATASET="video_metadata"
BQ_TABLE="segments"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
#############################

SA_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
PUBSUB_SA="service-${PROJECT_NUMBER}@gcs-project-accounts.iam.gserviceaccount.com"

echo "==> Building container image"
cd "$(dirname "$0")/.."
gcloud builds submit --tag "${IMAGE_NAME}" --project "${PROJECT_ID}"

echo "==> Deploying Cloud Run service: ${SERVICE_NAME}"
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_NAME}" \
  --region="${REGION}" \
  --platform=managed \
  --service-account="${SA_EMAIL}" \
  --memory=4Gi \
  --cpu=2 \
  --timeout=3600 \
  --concurrency=1 \
  --max-instances=5 \
  --no-allow-unauthenticated \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},REGION=${REGION},INPUT_BUCKET=${INPUT_BUCKET},OUTPUT_BUCKET=${OUTPUT_BUCKET},BQ_DATASET=${BQ_DATASET},BQ_TABLE=${BQ_TABLE}" \
  --project="${PROJECT_ID}"

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format="value(status.url)" \
  --project="${PROJECT_ID}")
echo "Cloud Run URL: ${SERVICE_URL}"

echo "==> Granting Pub/Sub permission to invoke Cloud Run"
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

echo "==> Granting token creator role to Pub/Sub service agent"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --quiet

echo "==> Creating Pub/Sub push subscription: ${SUBSCRIPTION_NAME}"
gcloud pubsub subscriptions create "${SUBSCRIPTION_NAME}" \
  --topic="${TOPIC_NAME}" \
  --push-endpoint="${SERVICE_URL}" \
  --push-auth-service-account="${SA_EMAIL}" \
  --ack-deadline=600 \
  --dead-letter-topic="${DEAD_LETTER_TOPIC}" \
  --max-delivery-attempts=5 \
  --min-retry-delay=10s \
  --max-retry-delay=600s \
  --project="${PROJECT_ID}" \
  2>/dev/null || echo "Subscription already exists, updating..."

# Update if it already existed
gcloud pubsub subscriptions update "${SUBSCRIPTION_NAME}" \
  --push-endpoint="${SERVICE_URL}" \
  --push-auth-service-account="${SA_EMAIL}" \
  --ack-deadline=600 \
  --dead-letter-topic="${DEAD_LETTER_TOPIC}" \
  --max-delivery-attempts=5 \
  --project="${PROJECT_ID}" \
  2>/dev/null || true

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo "Service URL: ${SERVICE_URL}"
echo "Subscription: ${SUBSCRIPTION_NAME}"
echo ""
echo "Test by uploading a video:"
echo "  gcloud storage cp test_video.mp4 gs://${INPUT_BUCKET}/"
echo ""
echo "Check logs:"
echo "  gcloud run services logs read ${SERVICE_NAME} --region=${REGION} --project=${PROJECT_ID}"
