#!/bin/bash

# Hassas URL'leri GitHub'dan çek (İmaj içinde URL bırakma) [cite: 1]
CONF_U="$(echo 'aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL0V4bWEwL3djL3JlZnMvaGVhZHMvbWFpbi91cmw=' | base64 -d)"
DYN_URL=$(curl -sL "$CONF_U" | tr -d '\n\r\t ')

export PROXY_URL="${DYN_URL}"
# Ortam değişkenlerini gizlemek için script bittiğinde temizlik yapacak olan Python'u çağır
exec python3 /engine.py
