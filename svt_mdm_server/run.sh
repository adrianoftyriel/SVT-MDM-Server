#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

# --- Add-on options ----------------------------------------------------------
export MDM_ENROLLMENT_SECRET="$(bashio::config 'enrollment_secret')"
export MDM_LOG_LEVEL="$(bashio::config 'log_level')"
export MDM_MQTT_PUSH="$(bashio::config 'mqtt_push')"
export MDM_HA_DISCOVERY="$(bashio::config 'ha_discovery')"
export MDM_DASHBOARD_ALLOWED_IPS="$(bashio::config 'dashboard_allowed_ips')"
export MDM_BACKUP_DIR="$(bashio::config 'backup_dir')"
export MDM_BACKUP_KEY="$(bashio::config 'backup_encryption_key')"
export MDM_EXTERNAL_URL="$(bashio::config 'external_url')"
export MDM_APK_URL="$(bashio::config 'apk_url')"
export MDM_DB_PATH="/data/mdm.db"
export MDM_HTTP_PORT="8099"

# --- MQTT service (injected by the Supervisor) -------------------------------
if bashio::services.available "mqtt"; then
    export MDM_MQTT_HOST="$(bashio::services mqtt 'host')"
    export MDM_MQTT_PORT="$(bashio::services mqtt 'port')"
    export MDM_MQTT_USERNAME="$(bashio::services mqtt 'username')"
    export MDM_MQTT_PASSWORD="$(bashio::services mqtt 'password')"
    export MDM_MQTT_TLS="$(bashio::services mqtt 'ssl')"
    bashio::log.info "MQTT broker configured at ${MDM_MQTT_HOST}:${MDM_MQTT_PORT}"
else
    bashio::log.warning "No MQTT service available; running in polling-only mode."
fi

bashio::log.info "Starting SVT MDM server on port ${MDM_HTTP_PORT}"
cd /app
# No --proxy-headers: the dashboard access check relies on the real TCP peer
# IP (the HA Supervisor for ingress). Trusting X-Forwarded-For would let a
# request through the public proxy spoof the ingress source address.
exec python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${MDM_HTTP_PORT}"
