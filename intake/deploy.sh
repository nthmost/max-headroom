#!/bin/bash
# deploy.sh — Install the intake web app on headroom.local
# Run this as a user with sudo access on headroom.local.
# The app runs as the 'max' user on port 8765.

set -euo pipefail

APP_DIR="/home/max/intake"
LOG_DIR="/var/log/transcode/intake"
SERVICE="intake"

echo "==> Creating app directory..."
sudo mkdir -p "$APP_DIR"
sudo cp -r . "$APP_DIR/"
sudo chown -R max:max "$APP_DIR"

echo "==> Creating log directory..."
sudo mkdir -p "$LOG_DIR"
sudo chown -R max:max "$LOG_DIR"

echo "==> Installing Python dependencies..."
sudo -u max pip3 install --user flask internetarchive

echo "==> Installing systemd service..."
sudo cp "$APP_DIR/intake.service" /etc/systemd/system/intake.service

echo ""
echo "IMPORTANT: Edit /etc/systemd/system/intake.service and set INTAKE_API_KEY"
echo "to something secure before starting the service."
echo ""

echo "==> To start the service:"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable --now intake"
echo "    sudo systemctl status intake"
echo ""
echo "App will be available at: http://headroom.local:8765/"
