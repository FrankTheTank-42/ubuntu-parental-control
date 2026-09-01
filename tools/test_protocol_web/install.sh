#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly SOURCE_DIR="$PROJECT_ROOT/tools/test_protocol_web"

root_prefix="/"
source_ods=""
replace_data=false
start_service=true

usage() {
  echo "Verwendung: sudo $0 --import-ods DATEI [--replace-data] [--root TESTZIEL] [--no-start]"
}

die() {
  echo "Fehler: $*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --import-ods)
      (($# >= 2)) || die "--import-ods benötigt einen Pfad"
      source_ods="$2"
      shift 2
      ;;
    --replace-data)
      replace_data=true
      shift
      ;;
    --root)
      (($# >= 2)) || die "--root benötigt einen Pfad"
      [[ -n "$2" && "$2" == /* ]] || die "--root muss ein absoluter Pfad sein"
      root_prefix="${2%/}"
      [[ -n "$root_prefix" ]] || root_prefix="/"
      shift 2
      ;;
    --no-start)
      start_service=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unbekannte Option: $1"
      ;;
  esac
done

[[ -f "$SOURCE_DIR/server.py" ]] || die "server.py fehlt"
[[ -f "$SOURCE_DIR/static/index.html" ]] || die "Weboberfläche fehlt"
command -v python3 >/dev/null || die "python3 fehlt"
if [[ "$root_prefix" == "/" && ${EUID} -ne 0 ]]; then
  die "die Systeminstallation muss als root laufen"
fi

prefix_path() {
  if [[ "$root_prefix" == "/" ]]; then
    printf '%s' "$1"
  else
    printf '%s%s' "$root_prefix" "$1"
  fi
}

readonly APP_DIR="$(prefix_path /usr/lib/ubuntu-parental-control-test-protocol)"
readonly STATE_DIR="$(prefix_path /var/lib/ubuntu-parental-control-test-protocol)"
readonly STATE_FILE="$STATE_DIR/state.json"
readonly UNIT_FILE="$(prefix_path /etc/systemd/system/ubuntu-parental-control-test-protocol.service)"

[[ ! -L "$APP_DIR" ]] || die "Programmverzeichnis darf kein symbolischer Link sein"
[[ ! -L "$STATE_DIR" ]] || die "Datenverzeichnis darf kein symbolischer Link sein"
[[ ! -L "$STATE_FILE" ]] || die "Teststand darf kein symbolischer Link sein"

if [[ ! -f "$STATE_FILE" && -z "$source_ods" ]]; then
  die "für die erste Installation ist --import-ods erforderlich"
fi
if [[ -n "$source_ods" ]]; then
  [[ -f "$source_ods" ]] || die "ODS-Datei nicht gefunden: $source_ods"
fi
if [[ -f "$STATE_FILE" && "$replace_data" == false && -n "$source_ods" ]]; then
  echo "Vorhandener Teststand bleibt erhalten; --import-ods wird ignoriert."
  source_ods=""
fi

staging_dir="$(mktemp -d)" || die "temporäres Verzeichnis konnte nicht erstellt werden"
trap 'rm -rf -- "$staging_dir"' EXIT
if [[ -n "$source_ods" ]]; then
  install -m 0600 -- "$source_ods" "$staging_dir/source.ods"
  python3 "$SOURCE_DIR/server.py" import-ods \
    "$staging_dir/source.ods" "$staging_dir/state.json"
else
  python3 "$SOURCE_DIR/server.py" validate-state "$STATE_FILE"
fi

if [[ "$root_prefix" == "/" ]]; then
  if ! id -u upc-testlog >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/ubuntu-parental-control-test-protocol \
      --shell /usr/sbin/nologin --user-group upc-testlog
  fi
  service_uid="$(id -u upc-testlog)"
  service_gid="$(id -g upc-testlog)"
  [[ "$service_uid" -gt 0 ]] || die "ungültiges Dienstkonto upc-testlog"
else
  service_uid="$(id -u)"
  service_gid="$(id -g)"
fi

if [[ "$root_prefix" == "/" ]] && systemctl is-active --quiet ubuntu-parental-control-test-protocol.service; then
  systemctl stop ubuntu-parental-control-test-protocol.service
fi

install -d -m 0755 "$APP_DIR" "$APP_DIR/static" "$(dirname "$UNIT_FILE")"
install -d -m 0750 -o "$service_uid" -g "$service_gid" "$STATE_DIR"
install -m 0755 "$SOURCE_DIR/server.py" "$APP_DIR/server.py"
install -m 0644 "$SOURCE_DIR/static/index.html" "$APP_DIR/static/index.html"
install -m 0644 "$SOURCE_DIR/static/app.js" "$APP_DIR/static/app.js"
install -m 0644 "$SOURCE_DIR/static/style.css" "$APP_DIR/static/style.css"
install -m 0644 "$SOURCE_DIR/ubuntu-parental-control-test-protocol.service" "$UNIT_FILE"

if [[ -n "$source_ods" ]]; then
  install -m 0600 -o "$service_uid" -g "$service_gid" \
    "$staging_dir/state.json" "$STATE_FILE"
fi

if [[ "$root_prefix" == "/" ]]; then
  systemctl daemon-reload
  if [[ "$start_service" == true ]]; then
    systemctl enable ubuntu-parental-control-test-protocol.service
    systemctl restart ubuntu-parental-control-test-protocol.service
    echo "Testprotokoll geöffnet unter: http://127.0.0.1:8780"
  else
    echo "Testdienst wurde installiert, aber nicht gestartet."
  fi
else
  echo "Testinstallation abgeschlossen: $root_prefix"
fi
