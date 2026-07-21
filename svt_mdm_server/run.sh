#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

# --- Add-on options ----------------------------------------------------------
export MDM_ENROLLMENT_SECRET="$(bashio::config 'enrollment_secret')"
export MDM_LOG_LEVEL="$(bashio::config 'log_level')"
export MDM_MQTT_PUSH="$(bashio::config 'mqtt_push')"
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
exec python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${MDM_HTTP_PORT}" \
    --proxy-headers \
    --forwarded-allow-ips "*"
