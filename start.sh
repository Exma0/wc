#!/bin/bash
# url dosyasından Cloudflare Worker adresini çek
CONF_U="$(echo 'aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL0V4bWEwL3djL3JlZnMvaGVhZHMvbWFpbi91cmw=' | base64 -d)"
DYN_URL=$(curl -sL "$CONF_U" | grep -oP 'https?://[^\s]+' | head -n 1)

export PROXY_URL="${DYN_URL}"
export PYTHONUNBUFFERED=1

exec python3 /app/engine.py
