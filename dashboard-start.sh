#!/bin/bash
# Dashboard startup script for node:18-slim
set -e

echo "[dashboard] Installing dependencies..."
mkdir -p /app
cd /app

# Install express
cat > package.json << 'PKG'
{
  "name": "yt-dashboard",
  "version": "1.0.0",
  "dependencies": {
    "express": "^4.18.2"
  }
}
PKG

npm install --production --quiet

echo "[dashboard] Downloading dashboard.js from GitHub..."
curl -fsSL "https://raw.githubusercontent.com/fridayaeye/yt-viewer/main/dashboard.js" -o dashboard.js

echo "[dashboard] Starting server..."
node dashboard.js
