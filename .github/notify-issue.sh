#!/usr/bin/env bash
# Prints the number of the open "Dashboard updates" issue, creating it if needed.
set -euo pipefail
title="Dashboard updates"
num=$(gh issue list --state open --search "\"$title\" in:title" --json number,title \
  --jq "map(select(.title == \"$title\")) | .[0].number // empty")
if [ -z "$num" ]; then
  url=$(gh issue create --title "$title" --body \
    "@${GITHUB_REPOSITORY_OWNER} the daily workflow comments here whenever the dashboard gets new data, and when a run fails. You are subscribed to this issue, so each comment arrives as a GitHub email and app notification.")
  num=${url##*/}
fi
echo "$num"
