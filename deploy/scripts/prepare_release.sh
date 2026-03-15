#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  prepare_release.sh --releases-root <path> --current <name> [--previous <name>] [--manifest <path>] [--apply]

Examples:
  ./deploy/scripts/prepare_release.sh --releases-root /opt/2tired/releases --current v3.1.4
  ./deploy/scripts/prepare_release.sh --releases-root /opt/2tired/releases --current v3.1.4 --apply
EOF
}

RELEASES_ROOT=""
CURRENT_RELEASE=""
PREVIOUS_RELEASE=""
MANIFEST_PATH=""
APPLY="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --releases-root)
      RELEASES_ROOT="${2:-}"; shift 2 ;;
    --current)
      CURRENT_RELEASE="${2:-}"; shift 2 ;;
    --previous)
      PREVIOUS_RELEASE="${2:-}"; shift 2 ;;
    --manifest)
      MANIFEST_PATH="${2:-}"; shift 2 ;;
    --apply)
      APPLY="true"; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1 ;;
  esac
done

if [[ -z "$RELEASES_ROOT" || -z "$CURRENT_RELEASE" ]]; then
  usage
  exit 1
fi

if [[ -z "$MANIFEST_PATH" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  MANIFEST_PATH="$SCRIPT_DIR/release_copy_manifest.txt"
fi

if [[ ! -d "$RELEASES_ROOT" ]]; then
  echo "Releases root not found: $RELEASES_ROOT" >&2
  exit 1
fi

CURRENT_PATH="$RELEASES_ROOT/$CURRENT_RELEASE"
if [[ ! -d "$CURRENT_PATH" ]]; then
  echo "Current release folder not found: $CURRENT_PATH" >&2
  exit 1
fi

if [[ ! -f "$MANIFEST_PATH" ]]; then
  echo "Manifest not found: $MANIFEST_PATH" >&2
  exit 1
fi

if [[ -z "$PREVIOUS_RELEASE" ]]; then
  PREVIOUS_RELEASE="$(find "$RELEASES_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | grep -v "^${CURRENT_RELEASE}$" | sort -V | tail -n 1 || true)"
  if [[ -z "$PREVIOUS_RELEASE" ]]; then
    echo "Cannot auto-detect previous release under: $RELEASES_ROOT" >&2
    exit 1
  fi
fi

PREVIOUS_PATH="$RELEASES_ROOT/$PREVIOUS_RELEASE"
if [[ ! -d "$PREVIOUS_PATH" ]]; then
  echo "Previous release folder not found: $PREVIOUS_PATH" >&2
  exit 1
fi

MODE="DRY-RUN"
if [[ "$APPLY" == "true" ]]; then
  MODE="APPLY"
fi

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$CURRENT_PATH/deploy_sync_${TS}.log"

{
  echo "[$MODE] releases_root=$RELEASES_ROOT"
  echo "[$MODE] previous=$PREVIOUS_PATH"
  echo "[$MODE] current=$CURRENT_PATH"
  echo "[$MODE] manifest=$MANIFEST_PATH"
} > "$LOG_FILE"

COPIED=0
SKIPPED=0

while IFS= read -r raw || [[ -n "$raw" ]]; do
  line="$(echo "$raw" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -z "$line" || "$line" == \#* ]] && continue

  SRC="$PREVIOUS_PATH/$line"
  DST="$CURRENT_PATH/$line"

  if [[ ! -e "$SRC" ]]; then
    echo "[SKIP] missing source: $line" | tee -a "$LOG_FILE"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  if [[ "$APPLY" != "true" ]]; then
    echo "[PLAN] $line" | tee -a "$LOG_FILE"
    continue
  fi

  mkdir -p "$(dirname "$DST")"
  rm -rf "$DST"
  cp -a "$SRC" "$DST"
  echo "[COPY] $line" | tee -a "$LOG_FILE"
  COPIED=$((COPIED + 1))
done < "$MANIFEST_PATH"

echo "[DONE] copied=$COPIED skipped=$SKIPPED mode=$MODE" | tee -a "$LOG_FILE"

if [[ "$APPLY" != "true" ]]; then
  echo "Dry-run complete. Add --apply to execute copy."
fi
