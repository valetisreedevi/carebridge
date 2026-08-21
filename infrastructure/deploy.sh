#!/usr/bin/env bash
# Deploys the CareBridge API to Cloud Run and points Cloud Scheduler at it.
#
#   PROJECT_ID=carecompanion-506011 ./infrastructure/deploy.sh
#
# Idempotent: safe to re-run.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-carebridge-api}"
BUCKET="${BUCKET:-carecompanion-media}"
# Gemini 3.x models are served from the global endpoint, not a region.
GENAI_LOCATION="${GENAI_LOCATION:-global}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.6-flash}"
# Caregiver/elder identity mode. Keep true once the web client has a
# Firebase sign-in screen; until then AUTH_ENABLED=false is only safe
# because the service itself is not publicly invokable.
AUTH_ENABLED="${AUTH_ENABLED:-true}"
# Turn on once the caregiver has clicked the link in their sign-up email;
# flipping it while an account is unconfirmed locks that account out.
REQUIRE_VERIFIED_EMAIL="${REQUIRE_VERIFIED_EMAIL:-false}"
# Semicolon-separated: --set-env-vars claims the comma. This must be set here
# rather than by hand, because --set-env-vars replaces the whole env block and
# would otherwise drop it, leaving the web client blocked by CORS.
# Cloud Run answers the web client on two hostnames: the project-number one
# and an older hashed one. A visitor on the hostname that is not listed here
# gets a browser that refuses every API call, so both are allowed.
PROJECT_NUMBER_EARLY="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
WEB_ORIGIN="${WEB_ORIGIN:-https://carebridge-web-${PROJECT_NUMBER_EARLY}.${REGION}.run.app}"
WEB_ORIGIN_ALT="${WEB_ORIGIN_ALT:-$(gcloud run services describe carebridge-web   --region "$REGION" --project "$PROJECT_ID" --format 'value(status.url)' 2>/dev/null || true)}"
CORS_ORIGINS_RAW="${CORS_ORIGINS_RAW:-${WEB_ORIGIN};${WEB_ORIGIN_ALT};http://localhost:5173;http://127.0.0.1:5173}"
SERVICE_ACCOUNT="carebridge-api@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA="carebridge-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Enabling APIs"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  fcm.googleapis.com \
  identitytoolkit.googleapis.com \
  --project "$PROJECT_ID"

echo "==> Service accounts"
for pair in "carebridge-api:CareBridge API" "carebridge-scheduler:CareBridge Scheduler"; do
  name="${pair%%:*}"
  display="${pair##*:}"
  gcloud iam service-accounts describe "${name}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --project "$PROJECT_ID" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$name" \
      --display-name "$display" --project "$PROJECT_ID"
done

echo "==> Roles for the API service account"
# Signed URLs need the account to sign as itself; everything else is the
# minimum the app actually calls.
for role in \
  roles/datastore.user \
  roles/storage.objectAdmin \
  roles/aiplatform.user \
  roles/firebase.sdkAdminServiceAgent \
  roles/iam.serviceAccountTokenCreator
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${SERVICE_ACCOUNT}" \
    --role "$role" --condition=None --quiet >/dev/null
done

echo "==> Cloud Build permissions"
# Building from source runs as the default compute service account, which on a
# fresh project can neither read the uploaded source nor write the built image.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
BUILD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for role in \
  roles/storage.objectViewer \
  roles/artifactregistry.writer \
  roles/logging.logWriter
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${BUILD_SA}" \
    --role "$role" --condition=None --quiet >/dev/null
done

echo "==> Worker token"
if ! gcloud secrets describe carebridge-worker-token --project "$PROJECT_ID" >/dev/null 2>&1; then
  # printf, not echo: a trailing newline ends up in the Cloud Run env var but
  # is stripped from the scheduler header by command substitution, and the two
  # then never match.
  printf '%s' "$(openssl rand -hex 32)" | gcloud secrets create carebridge-worker-token \
    --data-file=- --project "$PROJECT_ID"
fi
gcloud secrets add-iam-policy-binding carebridge-worker-token \
  --member "serviceAccount:${SERVICE_ACCOUNT}" \
  --role roles/secretmanager.secretAccessor \
  --project "$PROJECT_ID" --quiet >/dev/null

# Who may call the service at all, which is separate from who the app thinks
# you are. With AUTH_ENABLED the API verifies a Firebase token on every request,
# so it can be reachable; without it the only thing standing between a stranger
# and the data is Cloud Run itself, so it must not be.
if [ "$AUTH_ENABLED" = "true" ]; then
  INVOKER_FLAG=--allow-unauthenticated
else
  INVOKER_FLAG=--no-allow-unauthenticated
fi

echo "==> Deploying $SERVICE ($INVOKER_FLAG)"
gcloud run deploy "$SERVICE" --quiet \
  --source backend \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$SERVICE_ACCOUNT" \
  "$INVOKER_FLAG" \
  --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=${GENAI_LOCATION},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${GENAI_LOCATION},GOOGLE_GENAI_USE_VERTEXAI=TRUE,GCS_BUCKET_NAME=${BUCKET},GEMINI_MODEL=${GEMINI_MODEL},AUTH_ENABLED=${AUTH_ENABLED},REQUIRE_VERIFIED_EMAIL=${REQUIRE_VERIFIED_EMAIL},CORS_ORIGINS_RAW=${CORS_ORIGINS_RAW}" \
  --set-secrets "WORKER_TOKEN=carebridge-worker-token:latest" \
  --min-instances 0 \
  --max-instances 5 \
  --timeout 120

URL="$(gcloud run services describe "$SERVICE" \
  --region "$REGION" --project "$PROJECT_ID" --format 'value(status.url)')"
echo "==> Deployed at $URL"

echo "==> Scheduler"
gcloud run services add-iam-policy-binding "$SERVICE" \
  --member "serviceAccount:${SCHEDULER_SA}" \
  --role roles/run.invoker \
  --region "$REGION" --project "$PROJECT_ID" --quiet >/dev/null

TOKEN="$(gcloud secrets versions access latest \
  --secret carebridge-worker-token --project "$PROJECT_ID")"

# One pass a minute is what makes retry and escalation feel immediate.
if gcloud scheduler jobs describe carebridge-reminders \
  --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1
then
  ACTION=update
  # `update http` has no --headers; it takes --update-headers instead.
  HEADER_FLAG=--update-headers
else
  ACTION=create
  HEADER_FLAG=--headers
fi

gcloud scheduler jobs "$ACTION" http carebridge-reminders \
  --location "$REGION" \
  --project "$PROJECT_ID" \
  --schedule "* * * * *" \
  --uri "${URL}/api/internal/reminders/process" \
  --http-method POST \
  "$HEADER_FLAG" "X-Worker-Token=${TOKEN}" \
  --oidc-service-account-email "$SCHEDULER_SA" \
  --oidc-token-audience "$URL" \
  --attempt-deadline 60s

echo "==> Firestore and Storage rules"
gcloud firestore databases update --type firestore-native \
  --project "$PROJECT_ID" >/dev/null 2>&1 || true

echo
echo "Done."
echo "  API:       $URL"
echo "  Health:    curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" $URL/health"
echo "  Frontend:  build with VITE_API_URL=$URL"
echo "  Android:   ./gradlew installDebug -PapiBaseUrl=$URL"
