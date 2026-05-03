#!/bin/sh
# First-run bootstrap, then serve.
#
# DATA_ROOT (/data) is a persistent volume — empty on first boot. Seed it from
# the image's committed defaults, apply the schema, load locations + stations,
# then hand off to uvicorn. db init and seed are both idempotent, so this is
# safe to run on every container start.
set -e

mkdir -p /data

# Copy the committed config into the volume if it isn't there yet. After first
# run the operator edits /data/site.toml and /data/stations.toml directly.
for f in site.toml stations.toml; do
  if [ ! -f "/data/$f" ]; then
    cp "/app/data/$f" "/data/$f"
  fi
done

python -m app.db init
python -m app.seed

# --forwarded-allow-ips=* trusts the X-Forwarded-* headers from Caddy (the
# app is only reachable through it on the compose network), so request.base_url
# resolves to https — keeping canonical / og:url tags correct.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips='*'
