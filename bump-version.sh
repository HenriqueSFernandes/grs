#!/usr/bin/env bash
set -euo pipefail

# Read current versions
PYPROJECT_VERSION=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
INIT_VERSION=$(grep '__version__' injector/__init__.py | sed 's/.*__version__ = "\(.*\)"/\1/')

# Display
echo "Current versions:"
echo "  pyproject.toml:       $PYPROJECT_VERSION"
echo "  injector/__init__.py: $INIT_VERSION"
echo ""

# Warn if versions are out of sync
if [ "$PYPROJECT_VERSION" != "$INIT_VERSION" ]; then
    echo "Warning: versions are out of sync!"
    echo ""
fi

# Prompt
read -rp "Enter new version (e.g. 0.3.0): " NEW_VERSION

# Validate
if [[ ! "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Version must be in format X.Y.Z"
    exit 1
fi

# Check if tag already exists
if git rev-parse "v$NEW_VERSION" >/dev/null 2>&1; then
    echo "Error: Tag v$NEW_VERSION already exists."
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo "Warning: You have uncommitted changes."
    read -rp "Continue anyway? [y/N] " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Update files
sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" pyproject.toml
sed -i "s/__version__ = \".*\"/__version__ = \"$NEW_VERSION\"/" injector/__init__.py

# Commit and tag
git add pyproject.toml injector/__init__.py
git commit -m "Bump version to $NEW_VERSION"
git tag "v$NEW_VERSION"

echo ""
echo "Version bumped to $NEW_VERSION."
echo "Commit and tag created locally."
echo "Run the following to publish:"
echo ""
echo "  git push && git push --tags"
echo ""
