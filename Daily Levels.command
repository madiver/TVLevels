#!/bin/zsh
set -e
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
app_path=$(python3 panel/build.py)
/usr/bin/open "$app_path"
