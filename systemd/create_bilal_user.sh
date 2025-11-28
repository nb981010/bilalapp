#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <app_dir> [username]"
  exit 1
fi

APP_DIR="$1"
USER_NAME="${2:-bilal}"

echo "Creating system user '$USER_NAME' and preparing app directory ownership..."
if id -u "$USER_NAME" >/dev/null 2>&1; then
  echo "User $USER_NAME already exists."
else
  sudo useradd --system --create-home --shell /usr/sbin/nologin "$USER_NAME"
  echo "Created system user $USER_NAME"
fi

echo "Creating home dir and setting ownership..."
sudo mkdir -p /home/$USER_NAME
sudo chown -R $USER_NAME:$USER_NAME /home/$USER_NAME

echo "Ensuring app directory exists and is owned by $USER_NAME"
sudo mkdir -p "$APP_DIR"
sudo chown -R $USER_NAME:$USER_NAME "$APP_DIR"

DB_PATH="$APP_DIR/bilal_jobs.sqlite"
if [ -f "$DB_PATH" ]; then
  sudo chown $USER_NAME:$USER_NAME "$DB_PATH"
fi

echo "Done. The app directory $APP_DIR is now owned by $USER_NAME."
