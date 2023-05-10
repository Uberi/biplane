#!/usr/bin/env bash

most_recent_git_tag=$(git describe --tags $(git rev-list --tags --max-count=1))
sed -i.bak 's/"0.0.0+auto.0"/'"$most_recent_git_tag"'/g' biplane.py
sed -i.bak 's/"0.0.0+auto.0"/'"$most_recent_git_tag"'/g' pyproject.toml
python3 -m pip install --upgrade build twine
python3 -m build
mv biplane.py.bak biplane.py
mv pyproject.toml.bak pyproject.toml

echo 'for the next command, username is __token__ and password is the PyPI API token, beginning with "pypi-"'
python3 -m twine upload dist/*
