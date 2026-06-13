#!/bin/bash
# Deploy Shorts SaaS to VPS
# Usage: ./deploy.sh user@your-vps-ip

set -e

VPS="${1:?Usage: ./deploy.sh user@vps-ip}"
REMOTE_DIR="/opt/shorts-saas"

echo "=== Building frontend ==="
cd frontend
npm install
npm run build
cd ..

echo "=== Syncing to VPS ==="
rsync -avz --exclude='node_modules' --exclude='.git' --exclude='__pycache__' \
  --exclude='*.pyc' --exclude='frontend/node_modules' \
  ./ "$VPS:$REMOTE_DIR/"

echo "=== Deploying on VPS ==="
ssh "$VPS" "cd $REMOTE_DIR && docker compose build && docker compose up -d"

echo "=== Running migrations ==="
ssh "$VPS" "cd $REMOTE_DIR && docker compose exec -T api alembic upgrade head"

echo "=== Done! ==="
echo "Check: http://$(echo $VPS | cut -d@ -f2)/api/health"
