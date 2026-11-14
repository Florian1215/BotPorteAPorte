#!/bin/sh
# Generates a self-signed certificate on first start if none is provided in /etc/nginx/ssl.
# To use a real certificate (e.g. Let's Encrypt), put cert.pem and key.pem in the `certs` volume.
set -e
SSL_DIR=/etc/nginx/ssl
mkdir -p "$SSL_DIR"
if [ ! -f "$SSL_DIR/cert.pem" ] || [ ! -f "$SSL_DIR/key.pem" ]; then
    echo "Generating self-signed certificate for ${SERVER_NAME:-localhost}"
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
        -keyout "$SSL_DIR/key.pem" -out "$SSL_DIR/cert.pem" \
        -subj "/CN=${SERVER_NAME:-localhost}" \
        -addext "subjectAltName=DNS:${SERVER_NAME:-localhost},DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1
fi
