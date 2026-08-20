#!/usr/bin/env bash
# Builds the caregiver/elder web client and deploys it to Cloud Run.
#
#   PROJECT_ID=carecompanion-506011 ./infrastructure/deploy-web.sh
#
# Reads frontend/.env.local for VITE_* values. Vite bakes them into the bundle
# at build time, which is why the build runs here rather than inside Docker.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-carebridge-web}"

cd "$(dirname "$0")/../frontend"

if [ ! -f .env.local ]; then
  echo "frontend/.env.local is missing; see .env.example" >&2
  exit 1
fi

echo "==> Building"
npm ci --silent
npm run build

echo "==> Deploying $SERVICE"
gcloud run deploy "$SERVICE" --quiet \
  --source . \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 3

URL="$(gcloud run services describe "$SERVICE" \
  --region "$REGION" --project "$PROJECT_ID" --format 'value(status.url)')"

echo
echo "Web client: $URL"
echo "Make sure the API allows that origin: CORS_ORIGINS_RAW=$URL"
