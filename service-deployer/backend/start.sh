#!/bin/bash
set -e
cd /Users/hao/Desktop/feedmob/service-deployer-projects/service-deployer/service-deployer/backend

# Stub R2 env vars for local dev (image upload not used)
export R2_ACCOUNT_ID="dev-stub"
export R2_ACCESS_KEY_ID="dev-stub"
export R2_SECRET_ACCESS_KEY="dev-stub"
export R2_BUCKET_NAME="dev-stub"
export R2_PUBLIC_URL="https://stub.r2.dev"

# Sanity check
echo "R2_ACCOUNT_ID=$R2_ACCOUNT_ID"

exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
