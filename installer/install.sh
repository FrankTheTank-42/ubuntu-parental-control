#!/usr/bin/env bash
set -euo pipefail

readonly EXTENSION_ID="webfilter@ubuntu-parental-control.local"
readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

root_prefix="/"
xpi_path=""
chrome_extension_id=""
chrome_update_url="https://clients2.google.com/service/update2/crx"
start_service=true
restricted_uids=()
restricted_users_explicit=false

usage() {
  echo "Verwendung: sudo $0 --xpi PFAD [--restricted-user BENUTZER] [--chrome-extension-id ID] [--chrome-update-url URL] [--root TESTZIEL] [--no-start]"
}

die() {
  echo "Fehler: $*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --xpi)
      (($# >= 2)) || die "--xpi benötigt einen Pfad"
      xpi_path="$2"
      shift 2
      ;;
    --root)
      (($# >= 2)) || die "--root benötigt einen Pfad"
      [[ -n "$2" && "$2" == /* ]] || die "--root muss ein absoluter, nicht leerer Pfad sein"
      root_prefix="${2%/}"
      [[ -n "$root_prefix" ]] || root_prefix="/"
      shift 2
      ;;
    --chrome-extension-id)
      (($# >= 2)) || die "--chrome-extension-id benötigt eine ID"
      chrome_extension_id="$2"
      shift 2
      ;;
    --chrome-update-url)
      (($# >= 2)) || die "--chrome-update-url benötigt eine URL"
      chrome_update_url="$2"
      shift 2
      ;;
    --restricted-user)
      (($# >= 2)) || die "--restricted-user benötigt einen Kontonamen"
      restricted_uid="$(id -u -- "$2" 2>/dev/null)" || die "Ubuntu-Benutzerkonto nicht gefunden: $2"
      [[ "$restricted_uid" =~ ^[0-9]+$ && "$restricted_uid" -gt 0 ]] || die "ungültige UID für eingeschränktes Konto: $2"
      restricted_uids+=("$restricted_uid")
      restricted_users_explicit=true
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

[[ -n "$xpi_path" ]] || die "--xpi ist erforderlich (Firefox Stable benötigt ein signiertes XPI)"
[[ -f "$xpi_path" ]] || die "XPI nicht gefunden: $xpi_path"
command -v python3 >/dev/null || die "python3 fehlt"
command -v pkexec >/dev/null || die "pkexec (polkit) fehlt"
command -v openssl >/dev/null || die "openssl fehlt"
command -v base64 >/dev/null || die "base64 fehlt"
command -v gdbus >/dev/null || die "gdbus (GLib) fehlt"
if [[ -n "$chrome_extension_id" && ! "$chrome_extension_id" =~ ^[a-p]{32}$ ]]; then
  die "Chrome-Extension-ID muss aus 32 Zeichen a-p bestehen"
fi
if [[ "$chrome_update_url" != https://* ]]; then
  die "Chrome-Update-URL muss HTTPS verwenden"
fi

if [[ "$root_prefix" == "/" && ${EUID} -ne 0 ]]; then
  die "die Systeminstallation muss als root laufen"
fi

if [[ "$restricted_users_explicit" == false ]]; then
  detection_arguments=(--root "$root_prefix")
  if [[ "${SUDO_UID:-}" =~ ^[0-9]+$ && "${SUDO_UID}" -gt 0 ]]; then
    detection_arguments+=(--exclude-uid "$SUDO_UID")
  fi
  detected_users="$(
    python3 "$PROJECT_ROOT/installer/detect_restricted_users.py" "${detection_arguments[@]}"
  )" || die "Ubuntu-Benutzerkonten konnten nicht automatisch erkannt werden"
  if [[ -n "$detected_users" ]]; then
    while IFS=: read -r detected_uid detected_name; do
      [[ "$detected_uid" =~ ^[0-9]+$ && -n "$detected_name" ]] \
        || die "ungültiges Ergebnis der automatischen Benutzererkennung"
      restricted_uids+=("$detected_uid")
      echo "Eingeschränktes Konto automatisch erkannt: $detected_name (UID $detected_uid)"
    done <<< "$detected_users"
  else
    echo "Hinweis: Kein interaktives Nicht-Administratorkonto automatisch erkannt."
  fi
fi

python3 - "$xpi_path" "$EXTENSION_ID" <<'PY'
import json
import sys
import zipfile

path, expected_id = sys.argv[1:]
try:
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        archive_names = set(archive.namelist())
except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
    raise SystemExit(f"Fehler: ungültiges XPI: {exc}")
actual_id = manifest.get("browser_specific_settings", {}).get("gecko", {}).get("id")
if actual_id != expected_id:
    raise SystemExit(f"Fehler: XPI-ID ist {actual_id!r}, erwartet wird {expected_id!r}")
version = manifest.get("version", "0")
try:
    version_tuple = tuple(int(part) for part in version.split("."))
except (AttributeError, ValueError):
    raise SystemExit(f"Fehler: ungültige XPI-Version {version!r}")
if version_tuple < (0, 3, 0):
    raise SystemExit("Fehler: XPI ist älter als 0.3.0 und enthält die sichere Regelverwaltung noch nicht")
required = {"storage", "alarms", "contextMenus", "declarativeNetRequest", "nativeMessaging"}
if not required.issubset(set(manifest.get("permissions", []))):
    raise SystemExit("Fehler: XPI enthält nicht alle benötigten Webfilter-Berechtigungen")
required_hosts = {"http://*/*", "https://*/*"}
if not required_hosts.issubset(set(manifest.get("host_permissions", []))):
    raise SystemExit("Fehler: XPI enthält nicht alle für die Blockseite benötigten Host-Berechtigungen")
if not {"blocked/blocked.html", "blocked/blocked.css"}.issubset(archive_names):
    raise SystemExit("Fehler: XPI enthält die Blockseite nicht vollständig")
options_page = manifest.get("options_ui", {}).get("page")
if options_page != "options/options.html" or options_page not in archive_names:
    raise SystemExit("Fehler: XPI enthält die Regelverwaltungsseite nicht")
PY

prefix_path() {
  if [[ "$root_prefix" == "/" ]]; then
    printf '%s' "$1"
  else
    printf '%s%s' "$root_prefix" "$1"
  fi
}

readonly ETC_DIR="$(prefix_path /etc/ubuntu-parental-control)"
readonly POLICY_FILE="$(prefix_path /etc/firefox/policies/policies.json)"
readonly EXTENSION_DIR="$(prefix_path /etc/firefox/policies/extensions)"
readonly LIB_DIR="$(prefix_path /usr/lib/ubuntu-parental-control)"
readonly UPCCTL="$(prefix_path /usr/sbin/upcctl)"
readonly FIREFOX_CONSENT="$(prefix_path /usr/bin/upc-firefox-consent)"
readonly FIREFOX_CONSENT_DESKTOP="$(prefix_path /usr/share/applications/ubuntu-parental-control-firefox-consent.desktop)"
readonly FIREFOX_NATIVE_MANIFEST="$(prefix_path /usr/lib/mozilla/native-messaging-hosts/ubuntu_parental_control.json)"
readonly CHROME_NATIVE_MANIFEST="$(prefix_path /etc/opt/chrome/native-messaging-hosts/ubuntu_parental_control.json)"
readonly POLKIT_POLICY="$(prefix_path /usr/share/polkit-1/actions/local.ubuntu-parental-control.policy)"
readonly STATE_DIR="$(prefix_path /var/lib/ubuntu-parental-control)"
readonly RULE_HISTORY_DIR="$STATE_DIR/rule-history"
readonly LIVE_SIGNING_KEY="$STATE_DIR/live-signing-key.pem"
readonly SYSTEMD_DIR="$(prefix_path /etc/systemd/system)"
readonly STATE_FILE="$STATE_DIR/install-state.json"
readonly BACKUP_FILE="$STATE_DIR/policies.json.before-install"
readonly CHROME_POLICY="$(prefix_path /etc/opt/chrome/policies/managed/ubuntu-parental-control.json)"
readonly CHROME_BACKUP="$STATE_DIR/chrome-policy.json.before-install"
readonly LEGACY_XPI="$(prefix_path /usr/local/share/ubuntu-parental-control/webfilter.xpi)"

install -d -m 0755 "$ETC_DIR" "$(dirname "$POLICY_FILE")" "$EXTENSION_DIR" "$LIB_DIR" "$SYSTEMD_DIR"
install -d -m 0700 "$STATE_DIR"
install -d -m 0700 "$RULE_HISTORY_DIR"

[[ ! -L "$LIVE_SIGNING_KEY" ]] || die "Live-Signaturschlüssel darf kein symbolischer Link sein"
if [[ ! -f "$LIVE_SIGNING_KEY" ]]; then
  openssl genpkey \
    -algorithm EC \
    -pkeyopt ec_paramgen_curve:P-256 \
    -out "$LIVE_SIGNING_KEY" >/dev/null 2>&1
fi
chmod 0600 "$LIVE_SIGNING_KEY"
live_public_key_spki="$(openssl pkey -in "$LIVE_SIGNING_KEY" -pubout -outform DER 2>/dev/null | base64 -w0)"
[[ -n "$live_public_key_spki" ]] || die "öffentlicher Live-Signaturschlüssel konnte nicht erzeugt werden"

if [[ ! -f "$STATE_FILE" ]]; then
  if [[ -f "$POLICY_FILE" ]]; then
    install -m 0600 "$POLICY_FILE" "$BACKUP_FILE"
    policy_existed=true
  else
    policy_existed=false
  fi
  if [[ -f "$CHROME_POLICY" ]]; then
    install -m 0600 "$CHROME_POLICY" "$CHROME_BACKUP"
    chrome_policy_existed=true
  else
    chrome_policy_existed=false
  fi
  printf '{"chrome_policy_existed": %s, "policy_existed": %s}\n' \
    "$chrome_policy_existed" "$policy_existed" > "$STATE_FILE"
  chmod 0600 "$STATE_FILE"
fi

config_arguments=(
  --template "$PROJECT_ROOT/config/config.json"
  --output "$ETC_DIR/config.json"
  --chrome-update-url "$chrome_update_url"
  --live-public-key-spki "$live_public_key_spki"
)
if [[ -n "$chrome_extension_id" ]]; then
  config_arguments+=(--chrome-extension-id "$chrome_extension_id")
fi
for restricted_uid in "${restricted_uids[@]}"; do
  config_arguments+=(--restricted-uid "$restricted_uid")
done
python3 "$PROJECT_ROOT/installer/write_runtime_config.py" "${config_arguments[@]}"
if [[ ! -f "$ETC_DIR/rules.json" ]]; then
  install -m 0644 "$PROJECT_ROOT/config/rules.json" "$ETC_DIR/rules.json"
fi
if [[ ! -f "$STATE_DIR/user-domains.json" ]]; then
  printf '{"format_version":1,"users":{}}\n' > "$STATE_DIR/user-domains.json"
  chmod 0600 "$STATE_DIR/user-domains.json"
fi
install -m 0755 "$PROJECT_ROOT/daemon/daemon.py" "$LIB_DIR/daemon.py"
install -m 0755 "$PROJECT_ROOT/daemon/rule_validator.py" "$LIB_DIR/rule_validator.py"
install -m 0755 "$PROJECT_ROOT/daemon/managed_policy.py" "$LIB_DIR/managed_policy.py"
install -m 0755 "$PROJECT_ROOT/daemon/user_rules.py" "$LIB_DIR/user_rules.py"
install -m 0755 "$PROJECT_ROOT/daemon/control_server.py" "$LIB_DIR/control_server.py"
install -m 0755 "$PROJECT_ROOT/daemon/native_host.py" "$LIB_DIR/native_host.py"
install -m 0755 "$PROJECT_ROOT/daemon/admin_helper.py" "$LIB_DIR/admin_helper.py"
install -m 0755 "$PROJECT_ROOT/daemon/upcctl.py" "$LIB_DIR/upcctl.py"
install -D -m 0755 "$PROJECT_ROOT/installer/upcctl" "$UPCCTL"
install -D -m 0755 "$PROJECT_ROOT/installer/firefox_native_consent.py" "$FIREFOX_CONSENT"
install -D -m 0644 \
  "$PROJECT_ROOT/installer/ubuntu-parental-control-firefox-consent.desktop" \
  "$FIREFOX_CONSENT_DESKTOP"
install -m 0644 "$PROJECT_ROOT/daemon/ubuntu-parental-control.service" "$SYSTEMD_DIR/ubuntu-parental-control.service"
install -D -m 0644 "$PROJECT_ROOT/installer/local.ubuntu-parental-control.policy" "$POLKIT_POLICY"
install -m 0644 "$xpi_path" "$EXTENSION_DIR/webfilter.xpi"

if [[ "$root_prefix" == "/" ]]; then
  native_host_path="/usr/lib/ubuntu-parental-control/native_host.py"
else
  native_host_path="$LIB_DIR/native_host.py"
fi
native_manifest_arguments=(
  --host-path "$native_host_path"
  --config "$ETC_DIR/config.json"
  --firefox-output "$FIREFOX_NATIVE_MANIFEST"
  --chrome-output "$CHROME_NATIVE_MANIFEST"
)
if [[ -n "$chrome_extension_id" ]]; then
  native_manifest_arguments+=(--chrome-extension-id "$chrome_extension_id")
fi
python3 "$PROJECT_ROOT/installer/write_native_manifests.py" "${native_manifest_arguments[@]}"

if [[ "$root_prefix" == "/" ]]; then
  install_url="file:///etc/firefox/policies/extensions/webfilter.xpi"
else
  install_url="file://$EXTENSION_DIR/webfilter.xpi"
fi

python3 "$PROJECT_ROOT/installer/merge_firefox_policy.py" \
  --input "$POLICY_FILE" \
  --output "$POLICY_FILE" \
  --extension-id "$EXTENSION_ID" \
  --install-url "$install_url"

# Migration von Version 0.1: Dieser Ablageort ist für Firefox als Ubuntu-Snap
# nicht lesbar. Erst nach erfolgreichem Policy-Update entfernen.
rm -f -- "$LEGACY_XPI"
rmdir --ignore-fail-on-non-empty "$(dirname "$LEGACY_XPI")" 2>/dev/null || true

python3 "$LIB_DIR/daemon.py" \
  --config "$ETC_DIR/config.json" \
  --rules "$ETC_DIR/rules.json" \
  --check

python3 "$LIB_DIR/managed_policy.py" \
  --config "$ETC_DIR/config.json" \
  --rules "$ETC_DIR/rules.json" \
  --user-domains "$STATE_DIR/user-domains.json" \
  --firefox-policy "$POLICY_FILE" \
  --chrome-policy "$CHROME_POLICY"

if [[ "$root_prefix" == "/" ]]; then
  if command -v update-desktop-database >/dev/null; then
    update-desktop-database /usr/share/applications
  fi
  systemctl daemon-reload
  systemctl enable ubuntu-parental-control.service
  if [[ "$start_service" == true ]]; then
    systemctl restart ubuntu-parental-control.service
  fi
fi

echo "Installation abgeschlossen. Firefox vollständig neu starten und about:policies prüfen."
