#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$PROJECT_ROOT/build/test-tmp"
readonly TEST_ROOT="$(mktemp -d "$PROJECT_ROOT/build/test-tmp/installer.XXXXXXXXXX")"
trap 'rm -rf -- "$TEST_ROOT"' EXIT

python3 "$PROJECT_ROOT/tools/build_extension.py" >/dev/null
readonly XPI="$PROJECT_ROOT/dist/ubuntu-parental-control-webfilter-firefox-unsigned.xpi"
readonly POLICY="$TEST_ROOT/etc/firefox/policies/policies.json"
readonly CHROME_ID="abcdefghijklmnopabcdefghijklmnop"
readonly RESTRICTED_UID="2001"
readonly CHROME_POLICY="$TEST_ROOT/etc/opt/chrome/policies/managed/ubuntu-parental-control.json"

write_account_fixture() {
  local target_root="$1"
  mkdir -p "$target_root/etc"
  cat > "$target_root/etc/passwd" <<'EOF'
root:x:0:0:root:/root:/bin/bash
parent:x:2000:2000:Parent:/home/parent:/bin/bash
child:x:2001:2001:Child:/home/child:/bin/bash
service:x:2002:2002:Service:/var/lib/service:/usr/sbin/nologin
otheradmin:x:2003:2003:Other Admin:/home/otheradmin:/bin/bash
EOF
  cat > "$target_root/etc/group" <<'EOF'
root:x:0:
sudo:x:27:parent,otheradmin
parent:x:2000:
child:x:2001:
service:x:2002:
otheradmin:x:2003:
EOF
  cat > "$target_root/etc/login.defs" <<'EOF'
UID_MIN 1000
UID_MAX 60000
EOF
}

mkdir -p "$(dirname "$POLICY")"
write_account_fixture "$TEST_ROOT"
cat > "$POLICY" <<'JSON'
{
  "policies": {
    "DisableTelemetry": true
  }
}
JSON
cp "$POLICY" "$TEST_ROOT/original-policy.json"

"$PROJECT_ROOT/installer/install.sh" \
  --root "$TEST_ROOT" \
  --xpi "$XPI" \
  --chrome-extension-id "$CHROME_ID" \
  --no-start >/dev/null

python3 - "$POLICY" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)["policies"]
assert data["DisableTelemetry"] is True
assert data["BlockAboutConfig"] is True
entry = data["ExtensionSettings"]["webfilter@ubuntu-parental-control.local"]
assert entry["installation_mode"] == "force_installed"
assert "/etc/firefox/policies/extensions/webfilter.xpi" in entry["install_url"]
managed = data["3rdparty"]["Extensions"]["webfilter@ubuntu-parental-control.local"]
assert managed["protocol_version"] == 1
assert len(managed["revision"]) == 64
assert managed["revision"] == json.loads(managed["snapshot_json"])["revision"]
PY

python3 - "$CHROME_POLICY" "$CHROME_ID" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    policy = json.load(handle)
extension_id = sys.argv[2]
assert policy["ExtensionSettings"][extension_id]["installation_mode"] == "force_installed"
assert policy["IncognitoModeAvailability"] == 1
assert policy["BrowserGuestModeEnabled"] is False
assert policy["DeveloperToolsAvailability"] == 2
managed = policy["3rdparty"]["extensions"][extension_id]
assert managed["protocol_version"] == 1
PY

test -f "$TEST_ROOT/etc/firefox/policies/extensions/webfilter.xpi"
test -x "$TEST_ROOT/usr/lib/ubuntu-parental-control/rule_validator.py"
test -x "$TEST_ROOT/usr/lib/ubuntu-parental-control/upcctl.py"
test -x "$TEST_ROOT/usr/lib/ubuntu-parental-control/native_host.py"
test -x "$TEST_ROOT/usr/lib/ubuntu-parental-control/admin_helper.py"
test -x "$TEST_ROOT/usr/lib/ubuntu-parental-control/control_server.py"
test -x "$TEST_ROOT/usr/lib/ubuntu-parental-control/user_rules.py"
test -x "$TEST_ROOT/usr/sbin/upcctl"
test -x "$TEST_ROOT/usr/bin/upc-firefox-consent"
test -f "$TEST_ROOT/usr/share/applications/ubuntu-parental-control-firefox-consent.desktop"
grep -Fqx 'Exec=/usr/bin/upc-firefox-consent --from-uri %u' \
  "$TEST_ROOT/usr/share/applications/ubuntu-parental-control-firefox-consent.desktop"
grep -Fqx 'MimeType=x-scheme-handler/ubuntu-parental-control;' \
  "$TEST_ROOT/usr/share/applications/ubuntu-parental-control-firefox-consent.desktop"
test -f "$TEST_ROOT/etc/ubuntu-parental-control/rules.json"
python3 - "$TEST_ROOT/etc/ubuntu-parental-control/rules.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    rules = json.load(handle)
assert len(rules["blocks"]) == 1
block = rules["blocks"][0]
assert block["id"] == "default-block"
assert block["name"] == "Webseiten sperren"
assert block["enabled"] is True
assert block["action"] == "block"
assert block["user_permissions"]["add_domains"] is True
assert block["targets"] == {"domains": [], "url_patterns": [], "url_regex": []}
assert "schedule" not in block
PY
test -d "$TEST_ROOT/var/lib/ubuntu-parental-control/rule-history"
test "$(stat -c '%a' "$TEST_ROOT/var/lib/ubuntu-parental-control/rule-history")" = "700"
test -f "$TEST_ROOT/var/lib/ubuntu-parental-control/user-domains.json"
test "$(stat -c '%a' "$TEST_ROOT/var/lib/ubuntu-parental-control/user-domains.json")" = "600"
test -f "$TEST_ROOT/var/lib/ubuntu-parental-control/live-signing-key.pem"
test "$(stat -c '%a' "$TEST_ROOT/var/lib/ubuntu-parental-control/live-signing-key.pem")" = "600"
test -f "$TEST_ROOT/usr/lib/mozilla/native-messaging-hosts/ubuntu_parental_control.json"
test -f "$TEST_ROOT/etc/opt/chrome/native-messaging-hosts/ubuntu_parental_control.json"
test -f "$TEST_ROOT/usr/share/polkit-1/actions/local.ubuntu-parental-control.policy"
python3 - "$TEST_ROOT/usr/share/polkit-1/actions/local.ubuntu-parental-control.policy" <<'PY'
import sys
import xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
action = root.find("./action[@id='local.ubuntu-parental-control.manage']")
assert action is not None
assert action.findtext("./defaults/allow_active") == "auth_admin"
annotations = {item.attrib["key"]: item.text for item in action.findall("./annotate")}
assert annotations["org.freedesktop.policykit.exec.path"] == "/usr/lib/ubuntu-parental-control/admin_helper.py"
PY
python3 - "$TEST_ROOT/etc/ubuntu-parental-control/config.json" "$RESTRICTED_UID" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
assert config["restricted_users"] == [int(sys.argv[2])]
assert isinstance(config["live_public_key_spki"], str) and len(config["live_public_key_spki"]) > 80
PY
python3 - \
  "$TEST_ROOT/usr/lib/mozilla/native-messaging-hosts/ubuntu_parental_control.json" \
  "$TEST_ROOT/etc/opt/chrome/native-messaging-hosts/ubuntu_parental_control.json" \
  "$CHROME_ID" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    firefox = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    chrome = json.load(handle)
assert firefox["name"] == "ubuntu_parental_control"
assert firefox["allowed_extensions"] == ["webfilter@ubuntu-parental-control.local"]
assert chrome["allowed_origins"] == [f"chrome-extension://{sys.argv[3]}/"]
PY
python3 "$TEST_ROOT/usr/lib/ubuntu-parental-control/rule_validator.py" \
  "$PROJECT_ROOT/config/rules.example.json" >/dev/null
python3 "$TEST_ROOT/usr/lib/ubuntu-parental-control/upcctl.py" \
  --rules "$TEST_ROOT/etc/ubuntu-parental-control/rules.json" list >/dev/null

# Eine ältere gültige Installation mit leerer Blockliste wird beim Update um
# den neutralen Standard-Block ergänzt. Andere Profileinstellungen bleiben
# dabei erhalten.
python3 - "$TEST_ROOT/etc/ubuntu-parental-control/rules.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
rules = json.loads(path.read_text(encoding="utf-8"))
rules["profile"]["timezone"] = "UTC"
rules["blocks"] = []
path.write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")
PY
"$PROJECT_ROOT/installer/install.sh" \
  --root "$TEST_ROOT" \
  --xpi "$XPI" \
  --no-start >/dev/null
python3 - "$TEST_ROOT/etc/ubuntu-parental-control/rules.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    rules = json.load(handle)
assert rules["profile"]["timezone"] == "UTC"
assert [block["id"] for block in rules["blocks"]] == ["default-block"]
assert rules["blocks"][0]["targets"]["domains"] == []
PY

python3 - \
  "$TEST_ROOT/etc/ubuntu-parental-control/rules.json" \
  "$PROJECT_ROOT/config/rules.example.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
rules = json.loads(path.read_text(encoding="utf-8"))
example = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
rules["profile"]["timezone"] = "UTC"
# Alte Installationen durften identische sichtbare Namen verwenden. Beim
# Update müssen beide Blocks anhand ihrer technischen IDs erhalten bleiben.
rules["blocks"] = example["blocks"][:2]
rules["blocks"][1]["name"] = rules["blocks"][0]["name"]
path.write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")
PY
# A reinstall without repeating the Chrome ID preserves the already selected
# managed browsers as well as the administrator-edited rule file.
"$PROJECT_ROOT/installer/install.sh" \
  --root "$TEST_ROOT" \
  --xpi "$XPI" \
  --no-start >/dev/null
python3 - "$TEST_ROOT/etc/ubuntu-parental-control/rules.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    rules = json.load(handle)
assert rules["profile"]["timezone"] == "UTC"
assert rules["blocks"][0]["name"] == rules["blocks"][1]["name"]
assert rules["blocks"][0]["id"] != rules["blocks"][1]["id"]
PY
python3 - "$TEST_ROOT/etc/ubuntu-parental-control/config.json" "$CHROME_ID" "$RESTRICTED_UID" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
assert config["managed_browsers"] == ["firefox", "chrome"]
assert config["chrome_extension_id"] == sys.argv[2]
assert config["restricted_users"] == [int(sys.argv[3])]
PY

"$PROJECT_ROOT/installer/uninstall.sh" --root "$TEST_ROOT" --no-stop --prepare-only >/dev/null

python3 - "$POLICY" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    policies = json.load(handle)["policies"]
assert policies["DisableTelemetry"] is True
assert "ExtensionSettings" not in policies
assert policies["Extensions"]["Uninstall"] == []
PY

test -f "$TEST_ROOT/var/lib/ubuntu-parental-control/install-state.json"
python3 - "$TEST_ROOT/var/lib/ubuntu-parental-control/install-state.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
assert state["firefox_uninstall_phase"] == "unlock_pending"
assert state["uninstall_pending"] is False
PY

# Eine Eingabe bestätigt den ersten Firefox-Neustart. EOF unterbricht danach
# absichtlich vor dem zweiten Neustart, sodass die Zwischenphase prüfbar bleibt.
if printf '\n' | "$PROJECT_ROOT/installer/uninstall.sh" \
  --root "$TEST_ROOT" --no-stop >/dev/null 2>&1; then
  echo "Uninstaller wurde ohne zweiten Firefox-Neustart unerwartet abgeschlossen" >&2
  exit 1
fi
python3 - "$POLICY" "$TEST_ROOT/var/lib/ubuntu-parental-control/install-state.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    policies = json.load(handle)["policies"]
assert "webfilter@ubuntu-parental-control.local" in policies["Extensions"]["Uninstall"]
assert policies["ExtensionSettings"]["webfilter@ubuntu-parental-control.local"] == {
    "installation_mode": "blocked"
}
with open(sys.argv[2], encoding="utf-8") as handle:
    state = json.load(handle)
assert state["firefox_uninstall_phase"] == "uninstall_pending"
assert state["uninstall_pending"] is True
PY

# Die endgültige Policy darf nicht entfernt werden, solange Firefox die
# Extension noch in einem bekannten Profil registriert hat.
readonly FIREFOX_TEST_PROFILE="$TEST_ROOT/home/child/snap/firefox/common/.mozilla/firefox/test.default"
mkdir -p "$FIREFOX_TEST_PROFILE"
python3 - "$FIREFOX_TEST_PROFILE/extensions.json" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({"addons": [{"id": "webfilter@ubuntu-parental-control.local"}]}, handle)
PY
if "$PROJECT_ROOT/installer/uninstall.sh" \
  --root "$TEST_ROOT" --no-stop --finalize >/dev/null 2>&1; then
  echo "Uninstaller hat trotz vorhandener Profil-Extension finalisiert" >&2
  exit 1
fi
test -f "$TEST_ROOT/var/lib/ubuntu-parental-control/install-state.json"
test -f "$POLICY"
python3 - "$FIREFOX_TEST_PROFILE/extensions.json" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({"addons": []}, handle)
PY
"$PROJECT_ROOT/installer/uninstall.sh" --root "$TEST_ROOT" --no-stop --finalize >/dev/null
cmp "$POLICY" "$TEST_ROOT/original-policy.json"
test ! -e "$TEST_ROOT/usr/lib/ubuntu-parental-control/rule_validator.py"
test ! -e "$TEST_ROOT/usr/lib/ubuntu-parental-control/upcctl.py"
test ! -e "$TEST_ROOT/usr/lib/ubuntu-parental-control/native_host.py"
test ! -e "$TEST_ROOT/usr/lib/ubuntu-parental-control/admin_helper.py"
test ! -e "$TEST_ROOT/usr/sbin/upcctl"
test ! -e "$TEST_ROOT/usr/bin/upc-firefox-consent"
test ! -e "$TEST_ROOT/usr/share/applications/ubuntu-parental-control-firefox-consent.desktop"
test ! -e "$TEST_ROOT/var/lib/ubuntu-parental-control/rule-history"
test ! -e "$TEST_ROOT/var/lib/ubuntu-parental-control/user-domains.json"
test ! -e "$TEST_ROOT/var/lib/ubuntu-parental-control/user-domains.json.lock"
test ! -e "$TEST_ROOT/var/lib/ubuntu-parental-control/live-signing-key.pem"
test ! -e "$TEST_ROOT/usr/lib/mozilla/native-messaging-hosts/ubuntu_parental_control.json"
test ! -e "$TEST_ROOT/etc/opt/chrome/native-messaging-hosts/ubuntu_parental_control.json"
test ! -e "$TEST_ROOT/usr/share/polkit-1/actions/local.ubuntu-parental-control.policy"
test ! -e "$CHROME_POLICY"

readonly EMPTY_ROOT="$TEST_ROOT/without-original-policy"
write_account_fixture "$EMPTY_ROOT"
"$PROJECT_ROOT/installer/install.sh" --root "$EMPTY_ROOT" --xpi "$XPI" --no-start >/dev/null
"$PROJECT_ROOT/installer/uninstall.sh" --root "$EMPTY_ROOT" --no-stop --prepare-only >/dev/null
test -f "$EMPTY_ROOT/etc/firefox/policies/policies.json"
printf '\n' | "$PROJECT_ROOT/installer/uninstall.sh" \
  --root "$EMPTY_ROOT" --no-stop >/dev/null 2>&1 || true
"$PROJECT_ROOT/installer/uninstall.sh" --root "$EMPTY_ROOT" --no-stop --finalize >/dev/null
test ! -e "$EMPTY_ROOT/etc/firefox/policies/policies.json"

readonly EXISTING_CHROME_ROOT="$TEST_ROOT/existing-chrome-policy"
readonly EXISTING_CHROME_POLICY="$EXISTING_CHROME_ROOT/etc/opt/chrome/policies/managed/ubuntu-parental-control.json"
write_account_fixture "$EXISTING_CHROME_ROOT"
mkdir -p "$(dirname "$EXISTING_CHROME_POLICY")"
printf '{"HomepageLocation":"https://school.example/"}\n' > "$EXISTING_CHROME_POLICY"
cp "$EXISTING_CHROME_POLICY" "$EXISTING_CHROME_ROOT/original-chrome-policy.json"
"$PROJECT_ROOT/installer/install.sh" \
  --root "$EXISTING_CHROME_ROOT" \
  --xpi "$XPI" \
  --chrome-extension-id "$CHROME_ID" \
  --no-start >/dev/null
"$PROJECT_ROOT/installer/uninstall.sh" \
  --root "$EXISTING_CHROME_ROOT" --no-stop --prepare-only >/dev/null
printf '\n' | "$PROJECT_ROOT/installer/uninstall.sh" \
  --root "$EXISTING_CHROME_ROOT" --no-stop >/dev/null 2>&1 || true
"$PROJECT_ROOT/installer/uninstall.sh" \
  --root "$EXISTING_CHROME_ROOT" --no-stop --finalize >/dev/null
cmp "$EXISTING_CHROME_POLICY" "$EXISTING_CHROME_ROOT/original-chrome-policy.json"

readonly ONE_COMMAND_ROOT="$TEST_ROOT/one-command"
write_account_fixture "$ONE_COMMAND_ROOT"
"$PROJECT_ROOT/installer/install.sh" --root "$ONE_COMMAND_ROOT" --xpi "$XPI" --no-start >/dev/null
printf '\n\n' | "$PROJECT_ROOT/installer/uninstall.sh" --root "$ONE_COMMAND_ROOT" --no-stop >/dev/null
test ! -e "$ONE_COMMAND_ROOT/etc/firefox/policies/policies.json"

if "$PROJECT_ROOT/installer/install.sh" --root relative/path --xpi "$XPI" --no-start >/dev/null 2>&1; then
  echo "Relativer --root-Pfad wurde unerwartet akzeptiert" >&2
  exit 1
fi

printf 'kein xpi\n' > "$TEST_ROOT/invalid.xpi"
if "$PROJECT_ROOT/installer/install.sh" --root "$TEST_ROOT" --xpi "$TEST_ROOT/invalid.xpi" --no-start >/dev/null 2>&1; then
  echo "Ungültiges XPI wurde unerwartet akzeptiert" >&2
  exit 1
fi

echo "Installer- und Uninstaller-Test erfolgreich."
