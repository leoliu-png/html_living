#!/bin/bash
set -e
cd /Users/hao/Desktop/feedmob/service-deployer-projects/service-deployer/service-deployer/backend
cat > .env <<'EOF'
DATABASE_URL=postgresql+psycopg://service_deployer:service_deployer@localhost:5432/service_deployer
PUBLIC_BASE_URL=http://127.0.0.1:8000
API_TOKEN=dev-token-12345
SESSION_SECRET=local-dev-secret-do-not-use-in-prod
EOF
echo "=== .env created ==="
cat .env
