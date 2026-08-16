#!/usr/bin/env bash
# Runs as Vercel's build command. Writes assets/js/env.js so the static
# frontend knows where the Railway-hosted backend lives, using the
# BACKEND_API_URL environment variable set in the Vercel project settings
# (Project -> Settings -> Environment Variables).
set -euo pipefail

if [ -z "${BACKEND_API_URL:-}" ]; then
  echo "WARNING: BACKEND_API_URL is not set. Frontend will fall back to http://localhost:8000/api/v1"
  BACKEND_API_URL=""
fi

cat > assets/js/env.js <<EOF
window.__AUDITPULSE_API_BASE__ = "${BACKEND_API_URL}";
EOF

echo "Generated assets/js/env.js with API base: ${BACKEND_API_URL}"
