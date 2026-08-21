#!/usr/bin/env bash
# Prepares CareBridge's email links to point at this app's own /auth/action
# page instead of Firebase's hosted one.
#
#   PROJECT_ID=carecompanion-506011 ./infrastructure/configure-auth-links.sh
#
# Run this only after the web client carrying /auth/action is deployed.
#
# Two halves, and only one of them can be automated:
#
#   authorizedDomains  - set here.
#   action URL         - the Identity Platform admin API rejects it with
#                        EMAIL_TEMPLATE_UPDATE_NOT_ALLOWED on a Firebase-linked
#                        project; Firebase keeps email templates to its own
#                        console. This script prints what to click.
#
# Idempotent: safe to re-run.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
WEB_SERVICE="${WEB_SERVICE:-carebridge-web}"

# Cloud Run answers on two hostnames — the project-number one and an older
# hashed one — and status.url returns only whichever it prefers. Both reach
# the same service, so both are authorised and users can arrive on either.
PRIMARY_URL="${PRIMARY_URL:-https://${WEB_SERVICE}-$(gcloud projects describe "$PROJECT_ID" \
  --format 'value(projectNumber)').${REGION}.run.app}"
STATUS_URL="$(gcloud run services describe "$WEB_SERVICE" \
  --region "$REGION" --project "$PROJECT_ID" --format 'value(status.url)')"

CALLBACK="${PRIMARY_URL}/auth/action"

TOKEN="$(gcloud auth print-access-token)"
API="https://identitytoolkit.googleapis.com/admin/v2/projects/${PROJECT_ID}/config"

echo "==> Reading current auth config"
CURRENT="$(curl -fsS -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" "$API")"

# authorizedDomains is replaced wholesale by the PATCH, so the new hostnames
# are merged into the existing list rather than sent on their own.
BODY="$(PRIMARY_URL="$PRIMARY_URL" STATUS_URL="$STATUS_URL" python -c '
import json, os, sys

current = json.load(sys.stdin)
domains = list(current.get("authorizedDomains", []))

for url in (os.environ["PRIMARY_URL"], os.environ["STATUS_URL"]):
    host = url.removeprefix("https://").removeprefix("http://").rstrip("/")
    if host and host not in domains:
        domains.append(host)

print(json.dumps({"authorizedDomains": domains}))
' <<< "$CURRENT")"

echo "==> Authorising domains"
curl -fsS -X PATCH \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  -H "Content-Type: application/json" \
  --data "$BODY" \
  "${API}?updateMask=authorizedDomains" > /dev/null

python -c '
import json, sys
print("   " + "\n   ".join(json.loads(sys.argv[1])["authorizedDomains"]))
' "$BODY"

CURRENT_CALLBACK="$(python -c '
import json, sys
print(json.load(sys.stdin)["notification"]["sendEmail"].get("callbackUri", ""))
' <<< "$CURRENT")"

echo
if [ "$CURRENT_CALLBACK" = "$CALLBACK" ]; then
  echo "Action URL is already $CALLBACK — nothing left to do."
  exit 0
fi

cat <<MANUAL
One step left, and it has to be done by hand — Firebase does not accept email
template changes over the API (EMAIL_TEMPLATE_UPDATE_NOT_ALLOWED).

  1. https://console.firebase.google.com/project/${PROJECT_ID}/authentication/emails
  2. Pick "Email address verification", click the pencil icon
  3. Click "customize action URL"
  4. Paste: ${CALLBACK}
  5. Save

That URL is shared by every template, so password reset follows automatically.

Currently set to: ${CURRENT_CALLBACK:-<Firebase default>}
MANUAL
