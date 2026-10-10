#!/usr/bin/env bash
# App-host primitives for blue-green and serving (S3, given). Your CD decides when to call them.
#
#   deploy/web.sh init                       network, Traefik volume, routes; leaves Traefik alone
#   deploy/web.sh prepare                    init, then (re)start Traefik with this stack's config
#   deploy/web.sh live                       the colour taking traffic: blue, green or none
#   deploy/web.sh tag COLOUR                 the image tag a colour runs, or none
#   deploy/web.sh smoke COLOUR [GIT_SHA]     /version and /predict through Traefik, pinned to COLOUR
#   deploy/web.sh switch COLOUR              send all app traffic to COLOUR (the other keeps running)
#   deploy/web.sh serving-weights CHAMPION CHALLENGER [--if-missing]   split serving traffic (S8's canary)
#   deploy/web.sh reload ALIAS               make serving-ALIAS load what its MLflow alias points at now
#   deploy/web.sh status                     JSON: live colour, tags and commits, the models serving has loaded
#
# Runs on the app host (the self-hosted runner). Live weights live in the lab-traefik volume, not in
# the checkout, so a new checkout never resets which colour is live.
set -euo pipefail
cd "$(dirname "$0")/.."

VOLUME=lab-traefik NETWORK=lab
BUSYBOX=busybox:1.37.0
WEB=http://localhost:${HTTP_PORT:-80}

vol() { docker run --rm -i -v "$VOLUME:/d" "$BUSYBOX" "$@"; }

write() { # FILE: stdin into the volume, atomically (Traefik never sees a half-written file)
  vol sh -c "cat > /d/.$1.tmp && mv /d/.$1.tmp /d/$1"
}

# ALIAS METHOD PATH: call one serving container directly, not through Traefik. Traefik health-checks
# serving on /model, so a container without a model (no champion yet) gets no traffic from it, and
# /reload is how that container gets its first model.
serving() {
  docker exec "lab-serving-serving-$1-1" python -c '
import sys, urllib.error, urllib.request
req = urllib.request.Request("http://localhost:8001" + sys.argv[2], method=sys.argv[1])
try:
    print(urllib.request.urlopen(req, timeout=float(sys.argv[3])).read().decode())
except urllib.error.HTTPError as e:
    print(e.read().decode()); sys.exit(22)' "$2" "$3" "${4:-60}"
}

colour() {
  [[ "${1:-}" =~ ^(blue|green)$ ]] || { echo "colour must be blue or green, got '${1:-}'" >&2; exit 2; }
}

case ${1:-help} in
  init)
    docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
    docker volume inspect "$VOLUME" >/dev/null 2>&1 || docker volume create "$VOLUME" >/dev/null
    write routes.yaml <deploy/traefik/web/routes.yaml
    vol test -f /d/serving-live.yaml || "$0" serving-weights 100 0
    ;;
  prepare)
    "$0" init
    docker compose -f deploy/compose.web.yaml --profile secrets run --rm --quiet-pull app-secrets
    TRAEFIK_CONFIG_HASH=$(sha256sum deploy/traefik/web/traefik.yaml | cut -c1-12) \
      docker compose -f deploy/compose.web.yaml up -d --no-deps traefik
    ;;
  live)
    vol cat /d/app-live.color 2>/dev/null || echo none
    ;;
  tag)
    colour "${2:-}"
    image=$(docker inspect "lab-app-app-$2-1" --format '{{.Config.Image}}' 2>/dev/null || true)
    echo "${image##*:}" | sed 's/^$/none/'
    ;;
  smoke)
    colour "${2:-}"
    v=$(curl -fsS --retry 20 --retry-all-errors --retry-delay 3 -H "X-Lab-Color: $2" $WEB/version)
    echo "$2 /version: $v"
    if [[ -n "${3:-}" ]] && ! jq -e --arg sha "$3" '.git_sha == $sha' <<<"$v" >/dev/null; then
      echo "$2 runs $(jq -r .git_sha <<<"$v"), expected $3" >&2
      exit 1
    fi
    p=$(curl -fsS -H "X-Lab-Color: $2" -H 'Content-Type: application/json' $WEB/predict \
      -d '{"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_datetime": "2024-03-08T17:05:00"}')
    echo "$2 /predict: $p"
    ;;
  switch)
    colour "${2:-}"
    other=$([[ $2 == blue ]] && echo green || echo blue)
    write app-live.yaml <<EOF
# Written by deploy/web.sh switch $2 at $(date -u +%FT%TZ)
http:
  services:
    app-live:
      weighted:
        healthCheck: {}
        services:
          - {name: app-$2, weight: 100}
          - {name: app-$other, weight: 0}
EOF
    echo "$2" | write app-live.color
    echo "app traffic -> $2 ($other keeps running)"
    ;;
  serving-weights)
    champion=${2:?champion weight} challenger=${3:?challenger weight}
    [[ "$champion$challenger" =~ ^[0-9]+$ ]] || { echo "weights must be integers" >&2; exit 2; }
    if [[ "${4:-}" == --if-missing ]] && vol test -f /d/serving-live.yaml; then exit 0; fi
    write serving-live.yaml <<EOF
# Written by deploy/web.sh serving-weights at $(date -u +%FT%TZ)
http:
  services:
    serving-live:
      weighted:
        healthCheck: {}
        services:
          - {name: serving-champion, weight: $champion}
          - {name: serving-challenger, weight: $challenger}
EOF
    echo "serving traffic: champion $champion, challenger $challenger"
    ;;
  reload)
    [[ "${2:-}" =~ ^(champion|challenger)$ ]] || { echo "alias must be champion or challenger" >&2; exit 2; }
    serving "$2" POST /reload 300
    ;;
  status)
    model() { # one JSON value, whatever serving answered (a 503 body has .detail)
      local out
      out=$(serving "$1" GET /model 5 2>/dev/null) || true
      jq -c 'if .version then {version, alias, loaded_at} else {error: (.detail // "no answer")} end' <<<"${out:-{\}}" 2>/dev/null || echo '{"error": "no answer"}'
    }
    sha() { curl -fsS -m 5 -H "X-Lab-Color: $1" "$WEB/version" 2>/dev/null | jq -r '.git_sha // "none"' 2>/dev/null || echo none; }
    weight() { vol cat /d/serving-live.yaml 2>/dev/null | sed -n "s/.*name: serving-$1, weight: \([0-9]*\).*/\1/p"; }
    jq -n --arg live "$("$0" live)" --arg blue "$("$0" tag blue)" --arg green "$("$0" tag green)" \
      --arg blue_sha "$(sha blue)" --arg green_sha "$(sha green)" \
      --argjson champion "$(model champion)" --argjson challenger "$(model challenger)" \
      --arg wc "$(weight champion)" --arg wl "$(weight challenger)" \
      '{live: $live, colours: {blue: $blue, green: $green}, git_shas: {blue: $blue_sha, green: $green_sha},
        serving: {champion: $champion, challenger: $challenger},
        serving_weights: {champion: ($wc | tonumber? // null), challenger: ($wl | tonumber? // null)}}'
    ;;
  *)
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac
