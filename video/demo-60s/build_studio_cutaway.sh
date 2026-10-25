#!/usr/bin/env bash
# 4 s cutaway of the Tactopus Agent Studio for the outro, under "Code sets every number. The language
# model only writes the words.": first the header claim, then the decision-engine nodes (orange) against
# the language-model node (violet). Needs the dashboard on :8787.
set -euo pipefail
cd "$(dirname "$0")"
W=renders/studio
mkdir -p $W
FPS=25

uv run --no-project --with playwright python - "$W" <<'EOF'
import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto("http://127.0.0.1:8787/#/studio")
    pg.wait_for_timeout(3500)
    pg.screenshot(path=f"{sys.argv[1]}/studio.png")
    b.close()
EOF

box() { echo "drawbox=x=$1:y=$2:w=$3:h=$4:color=$5@0.12:t=fill,drawbox=x=$1:y=$2:w=$3:h=$4:color=$5:t=6"; }
hold() { # still dur cx cy Z boxes out
  local n; n=$(python3 -c "print(round($2*$FPS))")
  local z="1+($5-1)*(1-cos(PI*min(1,on/20)))/2+0.03*on/$n"
  ffmpeg -y -loglevel error -loop 1 -framerate $FPS -t "$2" -i "$1" -vf \
    "$6,scale=3840:2160,zoompan=z='$z':x='max(0,min(iw-iw/zoom,$3*2-iw/zoom/2))':y='max(0,min(ih-ih/zoom,$4*2-ih/zoom/2))':d=1:s=1920x1080:fps=$FPS,format=yuv420p" \
    -frames:v "$n" -c:v libx264 -crf 16 "$7"
}
ORANGE=0xF2552C
VIOLET=0x7C5CFF
hold $W/studio.png 1.8 1237 120 2.0 "$(box 1110 72 254 28 $ORANGE)" $W/c1.mp4
hold $W/studio.png 2.4 640 600 1.45 "$(box 188 524 232 150 $ORANGE),$(box 500 524 232 172 $ORANGE),$(box 812 524 232 150 $VIOLET)" $W/c2.mp4
printf "file '%s'\n" c1.mp4 c2.mp4 > $W/list.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i $W/list.txt -c copy renders/studio_cutaway.mp4
ffprobe -v error -show_entries format=duration -of csv=p=0 renders/studio_cutaway.mp4
