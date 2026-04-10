#!/usr/bin/env bash
#
# EFTA - GCP Project Setup Script
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - A GCP billing account linked
#
# Usage:
#   ./setup.sh <PROJECT_ID> [REGION]
#
# Example:
#   ./setup.sh efta-project us-central1

set -euo pipefail

PROJECT_ID="${1:?Usage: ./setup.sh <PROJECT_ID> [REGION]}"
REGION="${2:-us-central1}"
BUCKET_NAME="${PROJECT_ID}-documents"

echo "=== EFTA GCP Setup ==="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo "Bucket:  $BUCKET_NAME"
echo ""

# --- Create project (if it doesn't exist) ---
if gcloud projects describe "$PROJECT_ID" &>/dev/null; then
    echo "Project $PROJECT_ID already exists."
else
    echo "Creating project $PROJECT_ID..."
    gcloud projects create "$PROJECT_ID"
fi

gcloud config set project "$PROJECT_ID"

# --- Enable required APIs ---
echo ""
echo "Enabling APIs..."
APIS=(
    "firestore.googleapis.com"
    "storage.googleapis.com"
    "run.googleapis.com"
    "documentai.googleapis.com"
    "aiplatform.googleapis.com"
    "pubsub.googleapis.com"
    "secretmanager.googleapis.com"
    "cloudscheduler.googleapis.com"
    "cloudbuild.googleapis.com"
)

for api in "${APIS[@]}"; do
    echo "  Enabling $api..."
    gcloud services enable "$api" --quiet
done

# --- Create GCS Bucket ---
echo ""
echo "Creating GCS bucket gs://$BUCKET_NAME..."
if gsutil ls -b "gs://$BUCKET_NAME" &>/dev/null; then
    echo "  Bucket already exists."
else
    gsutil mb -l "$REGION" "gs://$BUCKET_NAME"
    # Create folder structure
    echo "" | gsutil cp - "gs://$BUCKET_NAME/originals/.keep"
    echo "" | gsutil cp - "gs://$BUCKET_NAME/text/.keep"
fi

# --- Create Firestore Database ---
echo ""
echo "Creating Firestore database (Native mode)..."
if gcloud firestore databases describe --database="(default)" &>/dev/null 2>&1; then
    echo "  Firestore database already exists."
else
    gcloud firestore databases create \
        --location="$REGION" \
        --type=firestore-native \
        --database="(default)"
fi

# --- Create Pub/Sub Topics ---
echo ""
echo "Creating Pub/Sub topics..."

for topic in "document-downloaded" "document-ocr-complete"; do
    if gcloud pubsub topics describe "$topic" &>/dev/null 2>&1; then
        echo "  Topic $topic already exists."
    else
        echo "  Creating topic $topic..."
        gcloud pubsub topics create "$topic"
    fi
done

# --- Create Pub/Sub Subscriptions ---
for topic in "document-downloaded" "document-ocr-complete"; do
    sub="${topic}-sub"
    if gcloud pubsub subscriptions describe "$sub" &>/dev/null 2>&1; then
        echo "  Subscription $sub already exists."
    else
        echo "  Creating subscription $sub..."
        gcloud pubsub subscriptions create "$sub" --topic="$topic"
    fi
done

# --- Create Secret Manager secret for victim encryption key ---
echo ""
echo "Creating Secret Manager secret for victim encryption key..."
if gcloud secrets describe "victim-encryption-key" &>/dev/null 2>&1; then
    echo "  Secret already exists."
else
    # Generate a random 256-bit key
    python3 -c "import secrets; print(secrets.token_hex(32))" | \
        gcloud secrets create "victim-encryption-key" \
            --data-file=- \
            --replication-policy="automatic"
    echo "  Secret created with auto-generated key."
fi

# --- Create service accounts ---
echo ""
echo "Creating service accounts..."

# Pipeline service account
SA_PIPELINE="efta-pipeline@${PROJECT_ID}.iam.gserviceaccount.com"
if gcloud iam service-accounts describe "$SA_PIPELINE" &>/dev/null 2>&1; then
    echo "  Pipeline service account already exists."
else
    gcloud iam service-accounts create "efta-pipeline" \
        --display-name="EFTA Pipeline"
fi

# Web service account
SA_WEB="efta-web@${PROJECT_ID}.iam.gserviceaccount.com"
if gcloud iam service-accounts describe "$SA_WEB" &>/dev/null 2>&1; then
    echo "  Web service account already exists."
else
    gcloud iam service-accounts create "efta-web" \
        --display-name="EFTA Web"
fi

# Grant roles to pipeline SA
echo "  Granting roles to pipeline service account..."
for role in \
    "roles/datastore.user" \
    "roles/storage.objectAdmin" \
    "roles/pubsub.publisher" \
    "roles/pubsub.subscriber" \
    "roles/documentai.apiUser" \
    "roles/aiplatform.user" \
    "roles/secretmanager.secretAccessor"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_PIPELINE" \
        --role="$role" \
        --quiet &>/dev/null
done

# Grant roles to web SA (read-only, no secret access)
echo "  Granting roles to web service account..."
for role in \
    "roles/datastore.viewer" \
    "roles/storage.objectViewer"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_WEB" \
        --role="$role" \
        --quiet &>/dev/null
done

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Create a .env file from .env.example:"
echo "     cp .env.example .env"
echo "     Edit .env with: GCP_PROJECT_ID=$PROJECT_ID, GCS_BUCKET_NAME=$BUCKET_NAME"
echo ""
echo "  2. Create a Document AI OCR processor in the GCP Console:"
echo "     https://console.cloud.google.com/ai/document-ai/processors"
echo "     Choose 'Document OCR' processor type."
echo "     Add the processor ID to your .env file."
echo ""
echo "  3. Install Python dependencies:"
echo "     cd pipeline && pip install -e '.[dev]'"
echo ""
echo "  4. Run the scraper:"
echo "     python -m pipeline.jobs.run_scraper"
