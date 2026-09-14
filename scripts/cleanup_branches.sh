#!/bin/bash
# Cleanup script for git branches

set -e

echo "🧹 Cleaning up merged and stale branches..."

# Get current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Fetch latest changes
git fetch --prune origin

# List all local branches except current
for branch in $(git branch | grep -v "\*" | grep -v "$CURRENT_BRANCH"); do
    # Check if branch is merged into main
    if git branch --merged main | grep -q "$branch"; then
        echo "Deleting merged branch: $branch"
        git branch -d "$branch"
    fi
done

# List remote-tracking branches that no longer exist on remote
git remote prune origin

echo "✅ Cleanup complete!"
