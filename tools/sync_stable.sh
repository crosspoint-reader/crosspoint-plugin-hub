#!/usr/bin/env bash
# Keep the bootstrap stable branch synchronized with main, but only while
# its installable plugin files still match the newest published stable release.
set -euo pipefail

expected_tag="${1:-}"
latest_tag="$(gh api "repos/$GITHUB_REPOSITORY/releases/latest" --jq '.tag_name')"
if [[ -n "$expected_tag" && "$expected_tag" != "$latest_tag" ]]; then
  echo "Not syncing older release $expected_tag; latest published stable release is $latest_tag"
  exit 0
fi

git fetch --force origin main stable "refs/tags/$latest_tag:refs/tags/$latest_tag"
python tools/check_release_metadata.py "$latest_tag"
if ! python tools/check_release_metadata.py "$latest_tag" --ref origin/main; then
  if [[ -n "$expected_tag" ]]; then
    echo "Release promotion failed: main does not match published $latest_tag" >&2
    exit 1
  fi
  echo "Skipping stable sync until main's new runtime version is published"
  exit 0
fi

# Catalog/doc changes after a release are fine. Never publish untagged
# firmware-facing JS, device settings, or manifest changes through stable.
if ! git merge-base --is-ancestor "$latest_tag" origin/main; then
  echo "Refusing to sync: published tag $latest_tag is not in main history" >&2
  exit 1
fi
if ! git diff --quiet "$latest_tag" origin/main -- manifest.json device.json plugin.js; then
  echo "Skipping stable sync: main has unreleased Plugin Hub runtime changes" >&2
  exit 0
fi

main_sha="$(git rev-parse origin/main)"
stable_sha="$(git rev-parse origin/stable)"
if [[ "$main_sha" == "$stable_sha" ]]; then
  echo "stable already equals main ($main_sha)"
  exit 0
fi

echo "Synchronizing stable with released main: $stable_sha -> $main_sha"
git push --force-with-lease="refs/heads/stable:$stable_sha" origin "$main_sha:refs/heads/stable"
