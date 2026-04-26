#!/bin/sh
# Installer for dankweather-govee-monitor.
#
# Usage:
#     curl -fsSL https://raw.githubusercontent.com/drakeapps/dankweather-govee-logger/master/install.sh | sh

set -eu

DEB_URL="https://github.com/drakeapps/dankweather-govee-logger/releases/latest/download/dankweather-govee-monitor.deb"
DEB_PATH="/tmp/dankweather-govee-monitor.deb"
CONF_PATH="/etc/dankweather-govee-monitor.conf"
SERVICE="dankweather-govee-monitor"

# Read from the controlling terminal so prompts still work when this script is
# invoked via `curl ... | sh` (in which case stdin is the script body).
ask() {
    printf '%s ' "$1" > /dev/tty
    IFS= read -r reply < /dev/tty
    printf '%s' "$reply"
}

echo "==> Downloading $DEB_URL"
curl -fL -o "$DEB_PATH" "$DEB_URL"

echo "==> Installing $DEB_PATH"
sudo apt install -y "$DEB_PATH"
rm -f "$DEB_PATH"

reply=$(ask "Edit $CONF_PATH now (recommended on first install)? [Y/n]")
case "$reply" in
    n|N|no|No|NO) ;;
    *) sudoedit "$CONF_PATH" ;;
esac

echo "==> Enabling and starting $SERVICE"
sudo systemctl enable "$SERVICE"
sudo systemctl restart "$SERVICE"

echo
echo "Done. Tail logs with:  journalctl -u $SERVICE -f"
