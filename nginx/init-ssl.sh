#!/bin/bash

if [ -z "${DOMAIN}" ]; then
  echo "Error: DOMAIN environment variable is not set."
  exit 1
fi

if [ -z "${EMAIL}" ]; then
  echo "Error: EMAIL environment variable is not set."
  exit 1
fi

DATA_PATH="./certbot"

if [ ! -e "$DATA_PATH/conf/ssl-dhparams.pem" ]; then
  echo "### Downloading recommended TLS parameters ..."
  mkdir -p "$DATA_PATH/conf"
  curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > "$DATA_PATH/conf/options-ssl-nginx.conf"
  curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem > "$DATA_PATH/conf/ssl-dhparams.pem"
fi

echo "### Requesting Let's Encrypt certificate for $DOMAIN ..."

# Enable staging mode if needed
staging=0 # Set to 1 if you're testing to avoid hit limits

arg_staging=""
if [ $staging != 0 ]; then arg_staging="--staging"; fi

docker compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $arg_staging \
    --email $EMAIL \
    -d $DOMAIN \
    --rsa-key-size 4096 \
    --agree-tos \
    --force-renewal \
    --non-interactive" certbot

echo "### Reloading nginx ..."
docker compose exec nginx nginx -s reload
