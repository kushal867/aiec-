#!/usr/bin/env bash
# Run this ON THE VPS as root (ssh root@176.103.218.98), after you've pushed
# the latest commit from your local machine. Deploys backend-py's no-LLM
# chat engine (real course/university/visa data, no GPU needed) via Docker.
set -euo pipefail

REPO_DIR="/opt/aiec"
REPO_URL="https://github.com/kushal867/aiec-.git"

echo "=== 1. Install Docker if missing ==="
if ! command -v docker &>/dev/null; then
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

echo "=== 2. Clone or update the repo ==="
if [ -d "$REPO_DIR/.git" ]; then
  cd "$REPO_DIR" && git pull origin main
else
  git clone "$REPO_URL" "$REPO_DIR"
  cd "$REPO_DIR"
fi

cd "$REPO_DIR/backend-py"

echo "=== 3. Write production .env (only if it doesn't already exist) ==="
if [ ! -f .env ]; then
  JWT_SECRET_VALUE=$(openssl rand -hex 48)
  cat > .env <<EOF
JWT_SECRET=${JWT_SECRET_VALUE}
ALLOWED_ORIGIN=https://asian.edu.np
ADMIN_ALLOWED_ORIGIN=https://crm.asian.edu.np
EOF
  echo "Wrote new .env with a freshly generated JWT_SECRET — back this file up somewhere safe."
  echo "IMPORTANT: edit ALLOWED_ORIGIN above to match your actual website domain(s) before going further."
else
  echo ".env already exists — leaving it as-is. Check it has JWT_SECRET, ALLOWED_ORIGIN set correctly."
fi

echo "=== 4. Build and start the container ==="
export JWT_SECRET=$(grep '^JWT_SECRET=' .env | cut -d= -f2)
export ALLOWED_ORIGIN=$(grep '^ALLOWED_ORIGIN=' .env | cut -d= -f2)
export ADMIN_ALLOWED_ORIGIN=$(grep '^ADMIN_ALLOWED_ORIGIN=' .env | cut -d= -f2)
docker compose up -d --build

echo "=== 5. Wait for container to be healthy ==="
sleep 8
docker compose ps

echo "=== 6. One-time data setup: seed courses, universities, users, and ingest knowledge base ==="
docker compose exec -T backend python -m app.scripts.seed_courses
docker compose exec -T backend python -m app.scripts.seed_universities
docker compose exec -T backend python -m app.scripts.seed_users
docker compose exec -T backend python -m app.ingestion.ingest

echo "=== 7. Verify ==="
curl -s http://localhost:3001/api/health && echo
curl -s -X POST http://localhost:3001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What courses are available in Canada?"}]}'
echo
echo "=== Done. The API is listening on port 3001 (container), mapped to host port 3001. ==="
echo "Next steps: set up a reverse proxy (nginx/Caddy) with HTTPS for a real domain,"
echo "and open port 3001 (or your proxy's port) in the VPS firewall if it's not already."
