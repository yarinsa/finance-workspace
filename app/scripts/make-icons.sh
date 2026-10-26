#!/usr/bin/env bash
# Rasterize the PWA icons from the SVG marks (needs `rsvg-convert`: brew install librsvg).
# Outputs are committed to public/, so this only reruns when the mark changes.
#   icon.svg            rounded tile, transparent corners  -> "any" icons, favicon
#   icon-full-bleed.svg square, no transparency            -> apple-touch-icon (iOS rounds it itself)
#   icon-maskable.svg   square, mark inside the 80% safe zone -> maskable icon
set -euo pipefail
cd "$(dirname "$0")/.."
r() { rsvg-convert -w "$2" -h "$2" "$1" -o "$3"; }
r public/icon.svg 192 public/icon-192.png
r public/icon.svg 512 public/icon-512.png
r scripts/icon-maskable.svg 512 public/icon-maskable-512.png
r scripts/icon-full-bleed.svg 180 public/apple-touch-icon.png
r public/icon.svg 32 public/favicon-32.png
