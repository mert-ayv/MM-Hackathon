#!/usr/bin/env bash
# Middle part of the demo video: dashboard replay of P01 (session 796f528a) with ElevenLabs voices.
# Replay times (V) come from the marks logged by record_replay.py, offset about 6.5 s into the recording.
# The score panel is blurred while the replay runs (its live estimate briefly shows 1.00); the last
# segment shows the official final score unblurred.
set -euo pipefail
cd "$(dirname "$0")"
SRC=$(ls -t renders/replay_router2/*.webm | head -1)
V=source/voices
OUT=renders/middle.mp4

ffmpeg -y -loglevel error -i "$SRC" \
  -i $V/v1_owner_offer.mp3 -i $V/v2_buyer_notice.mp3 -i $V/v3_backoffice_counter.mp3 \
  -i $V/v4_owner_fairpoint.mp3 -i $V/v6_owner_accept.mp3 \
  -filter_complex "
[0:v]fps=25,split=2[clean][forblur];
[forblur]split=2[base][panel];
[panel]crop=755:300:1130:188,boxblur=25:2[bl];
[base][bl]overlay=1130:188,split=5[b1][b2][b3][b4][b5];
[b1]trim=3.0:7.0,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=2.5[s1];
[b2]trim=7.0:8.85,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=6.65[s2];
[b3]trim=8.85:12.3,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=5.95[s3];
[b4]trim=12.3:30.0,setpts=(PTS-STARTPTS)/6[s4];
[b5]trim=30.0:31.8,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=5.5[s5];
[clean]trim=32.0:34.9,setpts=PTS-STARTPTS[s6];
[s1][s2][s3][s4][s5][s6]concat=n=6:v=1:a=0,format=yuv420p[v];
[1:a]adelay=200|200[a1];[2:a]adelay=6700|6700[a2];[3:a]adelay=15200|15200[a3];
[4:a]adelay=17500|17500[a4];[5:a]adelay=27650|27650[a5];
[a1][a2][a3][a4][a5]amix=inputs=5:normalize=0:duration=longest,apad[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -crf 18 -r 25 -c:a aac -b:a 192k -shortest "$OUT"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT"
