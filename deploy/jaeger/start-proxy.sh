#!/bin/sh
set -eu
: "${JAEGER_HTPASSWD:?Set JAEGER_HTPASSWD from the dashboard secret}"
umask 077
printf '%s\n' "$JAEGER_HTPASSWD" > /tmp/jaeger.htpasswd
unset JAEGER_HTPASSWD
exec nginx -g 'daemon off;'
