#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$PROJECT_ROOT/build/test-tmp"
readonly TEST_ROOT="$(mktemp -d "$PROJECT_ROOT/build/test-tmp/installer.XXXXXXXXXX")"
trap 'rm -rf -- "$TEST_ROOT"' EXIT

python3 "$PROJECT_ROOT/tools/build_extension.py" >/dev/null
readonly XPI="$PROJECT_ROOT/dist/ubuntu-parental-control-webfilter-unsigned.xpi"
readonly POLICY="$TEST_ROOT/etc/firefox/policies/policies.json"
readonly CHROME_ID="abcdefghijklmnopabcdefghijklmnop"
readonly CHROME_POLICY="$TEST_ROOT/etc/opt/chrome/policies/managed/ubuntu-parental-control.json"

mkdir -p "$(dirname "$POLICY")"
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
test -f "$TEST_ROOT/etc/ubuntu-parental-control/rules.json"
python3 "$TEST_ROOT/usr/lib/ubuntu-parental-control/rule_validator.py" \
  "$PROJECT_ROOT/config/rules.example.json" >/dev/null

python3 - "$TEST_ROOT/etc/ubuntu-parental-control/rules.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
rules = json.loads(path.read_text(encoding="utf-8"))
rules["profile"]["timezone"] = "UTC"
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
    assert json.load(handle)["profile"]["timezone"] == "UTC"
PY
python3 - "$TEST_ROOT/etc/ubuntu-parental-control/config.json" "$CHROME_ID" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
assert config["managed_browsers"] == ["firefox", "chrome"]
assert config["chrome_extension_id"] == sys.argv[2]
PY

"$PROJECT_ROOT/installer/uninstall.sh" --root "$TEST_ROOT" --no-stop --prepare-only >/dev/null

python3 - "$POLICY" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    policies = json.load(handle)["policies"]
assert policies["DisableTelemetry"] is True
assert "webfilter@ubuntu-parental-control.local" in policies["Extensions"]["Uninstall"]
assert "ExtensionSettings" not in policies
PY

test -f "$TEST_ROOT/var/lib/ubuntu-parental-control/install-state.json"
"$PROJECT_ROOT/installer/uninstall.sh" --root "$TEST_ROOT" --no-stop --finalize >/dev/null
cmp "$POLICY" "$TEST_ROOT/original-policy.json"
test ! -e "$TEST_ROOT/usr/lib/ubuntu-parental-control/rule_validator.py"
test ! -e "$CHROME_POLICY"

readonly EMPTY_ROOT="$TEST_ROOT/without-original-policy"
"$PROJECT_ROOT/installer/install.sh" --root "$EMPTY_ROOT" --xpi "$XPI" --no-start >/dev/null
"$PROJECT_ROOT/installer/uninstall.sh" --root "$EMPTY_ROOT" --no-stop --prepare-only >/dev/null
test -f "$EMPTY_ROOT/etc/firefox/policies/policies.json"
"$PROJECT_ROOT/installer/uninstall.sh" --root "$EMPTY_ROOT" --no-stop --finalize >/dev/null
test ! -e "$EMPTY_ROOT/etc/firefox/policies/policies.json"

readonly EXISTING_CHROME_ROOT="$TEST_ROOT/existing-chrome-policy"
readonly EXISTING_CHROME_POLICY="$EXISTING_CHROME_ROOT/etc/opt/chrome/policies/managed/ubuntu-parental-control.json"
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
"$PROJECT_ROOT/installer/uninstall.sh" \
  --root "$EXISTING_CHROME_ROOT" --no-stop --finalize >/dev/null
cmp "$EXISTING_CHROME_POLICY" "$EXISTING_CHROME_ROOT/original-chrome-policy.json"

readonly ONE_COMMAND_ROOT="$TEST_ROOT/one-command"
"$PROJECT_ROOT/installer/install.sh" --root "$ONE_COMMAND_ROOT" --xpi "$XPI" --no-start >/dev/null
printf '\n' | "$PROJECT_ROOT/installer/uninstall.sh" --root "$ONE_COMMAND_ROOT" --no-stop >/dev/null
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
