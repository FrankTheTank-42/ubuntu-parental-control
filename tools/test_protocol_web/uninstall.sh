#!/usr/bin/env bash
set -euo pipefail

purge_data=false

usage() {
  echo "Verwendung: sudo $0 [--purge-data]"
}

while (($#)); do
  case "$1" in
    --purge-data)
      purge_data=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Fehler: unbekannte Option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ${EUID} -ne 0 ]]; then
  echo "Fehler: die Deinstallation muss als root laufen" >&2
  exit 1
fi

systemctl disable --now ubuntu-parental-control-test-protocol.service 2>/dev/null || true
rm -f -- /etc/systemd/system/ubuntu-parental-control-test-protocol.service
rm -rf -- /usr/lib/ubuntu-parental-control-test-protocol
systemctl daemon-reload

if [[ "$purge_data" == true ]]; then
  rm -rf -- /var/lib/ubuntu-parental-control-test-protocol
  userdel upc-testlog 2>/dev/null || true
  echo "Testdienst und Testdaten wurden entfernt."
else
  echo "Testdienst entfernt; Daten bleiben unter /var/lib/ubuntu-parental-control-test-protocol erhalten."
fi
