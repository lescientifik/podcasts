#!/usr/bin/env bash
# Commit + push du nouvel épisode vers GitHub Pages.
# Usage : scripts/publish.sh epNNN "Titre de l'épisode"
set -euo pipefail

EP="${1:?Numéro d'épisode requis (ex: ep001)}"
TITLE="${2:?Titre requis}"

cd "$(dirname "$0")/.."

git add .
git commit -m "Nouvel épisode ${EP}: ${TITLE}"
git push
