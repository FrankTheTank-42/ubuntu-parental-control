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
readonly RULE_HISTORY_DIR="$STATE_DIR/rule-history"
readonly STATE_FILE="$STATE_DIR/install-state.json"
readonly BACKUP_FILE="$STATE_DIR/policies.json.before-install"
readonly CHROME_POLICY="$(prefix_path /etc/opt/chrome/policies/managed/ubuntu-parental-control.json)"
readonly CHROME_BACKUP="$STATE_DIR/chrome-policy.json.before-install"

[[ -f "$STATE_FILE" ]] || die "Installationsstatus fehlt; automatische Wiederherstellung ist nicht sicher"

read_state_bool() {
  python3 - "$STATE_FILE" "$1" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    value = json.load(handle).get(sys.argv[2], False)
print("true" if value else "false")
PY
}

read_state_value() {
  python3 - "$STATE_FILE" "$1" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    value = json.load(handle).get(sys.argv[2], "")
print(value if isinstance(value, str) else "")
PY
}

policy_existed="$(read_state_bool policy_existed)"
chrome_policy_existed="$(read_state_bool chrome_policy_existed)"
uninstall_pending="$(read_state_bool uninstall_pending)"
uninstall_phase="$(read_state_value firefox_uninstall_phase)"

# Statusdateien der vorherigen Uninstaller-Version hatten nur diesen booleschen
# Marker. Sie befanden sich bereits in der eigentlichen Uninstall-Phase.
if [[ -z "$uninstall_phase" && "$uninstall_pending" == true ]]; then
  uninstall_phase="uninstall_pending"
fi

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

verify_firefox_removed() {
  local output
  if output="$(python3 "$PROJECT_ROOT/installer/check_firefox_extension.py" \
    --root "$root_prefix" \
    --extension-id "$EXTENSION_ID" 2>&1)"; then
    echo "$output"
    return 0
  fi
  echo "$output" >&2
  echo >&2
  echo "Die Firefox-Uninstall-Policy bleibt aktiv." >&2
  echo "Firefox in allen betroffenen Konten vollständig starten und wieder schließen," >&2
  echo "danach uninstall.sh erneut ausführen." >&2
  return 1
}

write_uninstall_phase() {
  python3 - "$STATE_FILE" "$1" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open(encoding="utf-8") as handle:
    state = json.load(handle)
state["firefox_uninstall_phase"] = sys.argv[2]
state["uninstall_pending"] = sys.argv[2] == "uninstall_pending"
temporary = path.with_suffix(".tmp")
with temporary.open("w", encoding="utf-8", newline="\n") as handle:
    json.dump(state, handle, indent=2, sort_keys=True)
    handle.write("\n")
os.chmod(temporary, 0o600)
temporary.replace(path)
PY
}

write_firefox_policy() {
  local phase="$1"
  local base_arguments=()
  if [[ "$policy_existed" == true ]]; then
    [[ -f "$BACKUP_FILE" ]] || die "Policy-Backup fehlt; Abbruch zum Schutz vorhandener Daten"
    base_arguments=(--base "$BACKUP_FILE")
  fi
  python3 "$PROJECT_ROOT/installer/prepare_firefox_uninstall.py" \
    "${base_arguments[@]}" \
    --output "$POLICY_FILE" \
    --extension-id "$EXTENSION_ID" \
    --phase "$phase"
}

wait_for_unlock_restart() {
  echo
  echo "Firefox muss die bisher erzwungene Extension zuerst freigeben."
  echo "1. Firefox in jedem betroffenen Benutzerkonto vollständig starten."
  echo "2. Firefox wieder vollständig schließen."
  echo
  if ! read -r -p "Danach hier die Eingabetaste drücken, um die Entfernung vorzubereiten: "; then
    echo >&2
    echo "Der Uninstaller wurde unterbrochen. Nach dem Firefox-Neustart einfach erneut ausführen." >&2
    exit 2
  fi
  write_firefox_policy uninstall
  write_uninstall_phase uninstall_pending
  echo "Firefox-Uninstall-Policy aktiviert."
}

wait_for_uninstall_restart() {
  echo
  echo "Firefox muss die Extension jetzt selbst entfernen."
  echo "1. Firefox in jedem betroffenen Benutzerkonto vollständig starten."
  echo "2. Prüfen, dass die Extension unter about:addons verschwunden ist."
  echo "3. Firefox wieder vollständig schließen."
  echo
  if ! read -r -p "Danach hier die Eingabetaste drücken, um die Entfernung zu prüfen: "; then
    echo >&2
    echo "Der Uninstaller wurde unterbrochen. Nach dem Firefox-Neustart einfach erneut ausführen." >&2
    exit 2
  fi
  if ! verify_firefox_removed; then
    exit 3
  fi
  finish_uninstall
}

if [[ "$finalize" == true ]]; then
  [[ "$uninstall_phase" == "uninstall_pending" ]] || \
    die "Firefox muss vor dem Finalisieren beide Deinstallationsphasen verarbeiten"
  verify_firefox_removed || exit 3
  finish_uninstall
  exit 0
fi

if [[ "$uninstall_phase" == "unlock_pending" ]]; then
  if [[ "$prepare_only" == true ]]; then
    die "Deinstallation wartet auf den Firefox-Neustart zum Freigeben der Extension"
  fi
  echo "Eine unterbrochene Deinstallation wird fortgesetzt."
  wait_for_unlock_restart
  wait_for_uninstall_restart
  exit 0
fi

if [[ "$uninstall_phase" == "uninstall_pending" ]]; then
  if [[ "$prepare_only" == true ]]; then
    die "Deinstallation wartet auf den Firefox-Neustart zum Entfernen der Extension"
  fi
  echo "Eine unterbrochene Deinstallation wird fortgesetzt."
  wait_for_uninstall_restart
  exit 0
fi

if [[ "$root_prefix" == "/" ]]; then
  if [[ "$stop_service" == true ]]; then
    systemctl disable --now ubuntu-parental-control.service 2>/dev/null || true
  else
    systemctl disable ubuntu-parental-control.service 2>/dev/null || true
  fi
fi

write_firefox_policy unlock
write_uninstall_phase unlock_pending

rm -f -- "$(prefix_path /etc/systemd/system/ubuntu-parental-control.service)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/daemon.py)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/rule_validator.py)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/managed_policy.py)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/user_rules.py)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/control_server.py)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/native_host.py)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/admin_helper.py)"
rm -f -- "$(prefix_path /usr/lib/ubuntu-parental-control/upcctl.py)"
rm -f -- "$(prefix_path /usr/sbin/upcctl)"
rm -f -- "$(prefix_path /usr/bin/upc-firefox-consent)"
rm -f -- "$(prefix_path /usr/share/applications/ubuntu-parental-control-firefox-consent.desktop)"
rm -f -- "$(prefix_path /var/lib/ubuntu-parental-control/rules.last-known-good.json)"
rm -f -- "$(prefix_path /var/lib/ubuntu-parental-control/user-domains.json)"
rm -f -- "$(prefix_path /var/lib/ubuntu-parental-control/user-domains.json.lock)"
rm -f -- "$(prefix_path /var/lib/ubuntu-parental-control/live-signing-key.pem)"
rm -f -- "$(prefix_path /usr/lib/mozilla/native-messaging-hosts/ubuntu_parental_control.json)"
rm -f -- "$(prefix_path /etc/opt/chrome/native-messaging-hosts/ubuntu_parental_control.json)"
rm -f -- "$(prefix_path /usr/share/polkit-1/actions/local.ubuntu-parental-control.policy)"
rm -rf -- "$RULE_HISTORY_DIR"
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
  if command -v update-desktop-database >/dev/null; then
    update-desktop-database /usr/share/applications
  fi
  systemctl daemon-reload
fi

echo "Firefox-Freigabephase vorbereitet."
if [[ "$prepare_only" == true ]]; then
  exit 0
fi
wait_for_unlock_restart
wait_for_uninstall_restart
