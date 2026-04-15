#!/bin/sh
# Replace the placeholder in built JS files with the actual runtime env var
PLACEHOLDER="__VITE_API_URL_PLACEHOLDER__"
ACTUAL="${VITE_API_URL:-http://localhost:8000}"

echo "Injecting API URL: $ACTUAL"
find /usr/share/nginx/html/assets -name "*.js" -exec sed -i "s|${PLACEHOLDER}|${ACTUAL}|g" {} \;

exec nginx -g "daemon off;"
