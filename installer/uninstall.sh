#!/usr/bin/env bash
set -euo pipefail

readonly EXTENSION_ID="webfilter@ubuntu-parental-control.local"
readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

root_prefix="/"
stop_service=true
finalize=false
prepare_only=false

die() {
  echo "Fehler: $*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --root)
      (($# >= 2)) || die "--root benötigt einen Pfad"
      [[ -n "$2" && "$2" == /* ]] || die "--root muss ein absoluter, nicht leerer Pfad sein"
      root_prefix="${2%/}"
      [[ -n "$root_prefix" ]] || root_prefix="/"
      shift 2
      ;;
    --no-stop)
      stop_service=false
      shift
      ;;
    --finalize)
      finalize=true
      shift
      ;;
    --prepare-only)
      prepare_only=true
      shift
      ;;
    -h|--help)
      echo "Verwendung: sudo $0 [--root TESTZIEL] [--no-stop]"
      exit 0
      ;;
    *)
      die "unbekannte Option: $1"
      ;;
  esac
done

if [[ "$root_prefix" == "/" && ${EUID} -ne 0 ]]; then
  die "die Systemdeinstallation muss als root laufen"
fi

prefix_path() {
  if [[ "$root_prefix" == "/" ]]; then
    printf '%s' "$1"
  else
    printf '%s%s' "$root_prefix" "$1"
  fi
}

readonly POLICY_FILE="$(prefix_path /etc/firefox/policies/policies.json)"
readonly STATE_DIR="$(prefix_path /var/lib/ubuntu-parental-control)"
readonly STATE_FILE="$STATE_DIR/install-state.json"
readonly BACKUP_FILE="$STATE_DIR/policies.json.before-install"
readonly CHROME_POLICY="$(prefix_path /etc/opt/chrome/policies/managed/ubuntu-parental-control.json)"
readonly CHROME_BACKUP="$STATE_DIR/chrome-policy.json.before-install"

[[ -f "$STATE_FILE" ]] || die "Installationsstatus fehlt; automatische Wiederherstellung ist nicht sicher"

read_state() {
  python3 - "$STATE_FILE" "$1" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    value = json.load(handle).get(sys.argv[2], False)
print("true" if value else "false")
PY
}

policy_existed="$(read_state policy_existed)"
chrome_policy_existed="$(read_state chrome_policy_existed)"
uninstall_pending="$(read_state uninstall_pending)"

restore_original_policy() {
  if [[ "$policy_existed" == true ]]; then
    [[ -f "$BACKUP_FILE" ]] || die "Policy-Backup fehlt; Abbruch zum Schutz vorhandener Daten"
    install -D -m 0644 "$BACKUP_FILE" "$POLICY_FILE"
  else
    rm -f -- "$POLICY_FILE"
  fi
}

restore_original_chrome_policy() {
  if [[ "$chrome_policy_existed" == true ]]; then
    [[ -f "$CHROME_BACKUP" ]] || die "Chrome-Policy-Backup fehlt; Abbruch zum Schutz vorhandener Daten"
    install -D -m 0644 "$CHROME_BACKUP" "$CHROME_POLICY"
  else
    rm -f -- "$CHROME_POLICY"
  fi
}

finish_uninstall() {
  restore_original_policy
  restore_original_chrome_policy
  rm -f -- "$STATE_FILE" "$BACKUP_FILE" "$CHROME_BACKUP"
  rmdir --ignore-fail-on-non-empty \
    "$STATE_DIR" \
    "$(dirname "$POLICY_FILE")/extensions" \
    "$(dirname "$CHROME_POLICY")" 2>/dev/null || true
  if [[ "$root_prefix" == "/" ]]; then
    systemctl daemon-reload
  fi
  echo "Deinstallation abgeschlossen; ursprüngliche Firefox-Policy wiederhergestellt."
}

wait_for_firefox_restart() {
  echo
  echo "Firefox muss die Extension jetzt einmal selbst entfernen."
  echo "1. Firefox in jedem betroffenen Benutzerkonto vollständig starten."
  echo "2. Prüfen, dass die Extension unter about:addons verschwunden ist."
  echo "3. Firefox wieder vollständig schließen."
  echo
  if ! read -r -p "Danach hier die Eingabetaste drücken, um automatisch aufzuräumen: "; then
    echo >&2
    echo "Der Uninstaller wurde unterbrochen. Nach dem Firefox-Neustart einfach erneut ausführen." >&2
    exit 2
  fi
  finish_uninstall
}

if [[ "$finalize" == true ]]; then
  [[ "$uninstall_pending" == true ]] || die "keine ausstehende Firefox-Deinstallation gefunden"
  finish_uninstall
  exit 0
fi

if [[ "$uninstall_pending" == true ]]; then
  if [[ "$prepare_only" == true ]]; then
    die "Deinstallation wartet bereits auf einen Firefox-Neustart"
  fi
  echo "Eine unterbrochene Deinstallation wird fortgesetzt."
  wait_for_firefox_restart
  exit 0
fi

if [[ "$root_prefix" == "/" ]]; then
  if [[ "$stop_service" == true ]]; then
    systemctl disable --now ubuntu-parental-control.service 2>/dev/null || true
  else
    systemctl disable ubuntu-parental-control.service 2>/dev/null || true
  fi
fi

base_arguments=()
if [[ "$policy_existed" == true ]]; then
  [[ -f "$BACKUP_FILE" ]] || die "Policy-Backup fehlt; Abbruch zum Schutz vorhandener Daten"
  base_arguments=(--base "$BACKUP_FILE")
fi
python3 "$PROJECT_ROOT/installer/prepare_firefox_uninstall.py" \
  "${base_arguments[@]}" \
  --output "$POLICY_FILE" \
  --extension-id "$EXTENSION_ID"

python3 - "$STATE_FILE" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open(encoding="utf-8") as handle:
    state = json.load(handle)
state["uninstall_pending"] = True
temporary = path.with_suffix(".tmp")
with temporary.open("w", encoding="utf-8", newline="\n") as handle:
    json.dump(state, handle, indent=2, sort_keys=True)
    handle.write("\n")
os.chmod(temporary, 0o600)
temporary.replace(path)
PY

rm -f -- "$(prefix_path /etc/systemd/system/ubuntu-parental-control.service)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/daemon.py)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/rule_validator.py)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/managed_policy.py)"
rm -f -- "$(prefix_path /var/lib/ubuntu-parental-control/rules.last-known-good.json)"
rm -f -- "$(prefix_path /etc/firefox/policies/extensions/webfilter.xpi)"
rm -f -- "$(prefix_path /usr/local/share/ubuntu-parental-control/webfilter.xpi)"
rm -f -- "$(prefix_path /etc/ubuntu-parental-control/config.json)"
rm -f -- "$(prefix_path /etc/ubuntu-parental-control/rules.json)"
restore_original_chrome_policy

rmdir --ignore-fail-on-non-empty \
  "$(prefix_path /usr/lib/ubuntu-parental-control)" \
  "$(prefix_path /etc/firefox/policies/extensions)" \
  "$(prefix_path /usr/local/share/ubuntu-parental-control)" \
  "$(prefix_path /etc/ubuntu-parental-control)" \
  "$STATE_DIR" 2>/dev/null || true

if [[ "$root_prefix" == "/" ]]; then
  systemctl daemon-reload
fi

echo "Firefox-Deinstallation vorbereitet."
if [[ "$prepare_only" == true ]]; then
  exit 0
fi
wait_for_firefox_restart
