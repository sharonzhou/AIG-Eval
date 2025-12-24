#!/usr/bin/env bash
set -euo pipefail

# Clone AMD-AGI/AIG-Eval-Internal-Tasks into tasks/AIG-Eval-Internal-Tasks (no extra nesting)
script_dir="$(cd "$(dirname "$0")" && pwd)"
target_dir="$script_dir/AIG-Eval-Internal-Tasks"

mkdir -p "$target_dir"

# If already cloned, skip
if [ -d "$target_dir/.git" ]; then
  echo "Repo already present at ${target_dir} (skipping clone)."
  exit 0
fi

# Avoid cloning into a non-empty dir
if [ "$(ls -A "$target_dir")" ]; then
  echo "Target directory ${target_dir} is not empty. Please clean it before cloning."
  exit 1
fi

echo "Cloning AIG-Eval-Internal-Tasks into ${target_dir}"
git clone git@github.com:AMD-AGI/AIG-Eval-Internal-Tasks.git "$target_dir"

echo "Done. Files are now directly under ${target_dir}"
