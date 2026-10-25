#!/usr/bin/env bash
# Middle part v2: dashboard replay of P01 (session 796f528a), ElevenLabs voices (v2), and per scene a
# smooth zoom onto the key line with an orange highlight box. Replay times (V) are seconds into the
# 125 % recording (replay_router2); the live score panel is blurred until the deal is accepted.
set -euo pipefail
cd "$(dirname "$0")"
SRC=$(ls -t renders/replay_router2/*.webm | head -1)
V=source/voices/v2
W=renders/mid2
mkdir -p $W
FPS=25
ORANGE=0xF2552C

# 1. Blurred copy of the replay (score panel hidden) and stills for the zoom holds.
ffmpeg -y -loglevel error -i "$SRC" -filter_complex \
  "[0:v]fps=$FPS,split[a][b];[b]crop=755:300:1130:188,boxblur=25:2[bl];[a][bl]overlay=1130:188" \
  -c:v libx264 -crf 14 -an $W/blurred.mp4
still() { ffmpeg -y -loglevel error -ss "$2" -i "$1" -frames:v 1 "$3"; }
still $W/blurred.mp4 4.95 $W/k0.png
still $W/blurred.mp4 8.80 $W/k1.png
still $W/blurred.mp4 12.25 $W/k2.png
ffmpeg -y -loglevel error -i "$SRC" -vf fps=$FPS -c:v libx264 -crf 14 -an $W/clean.mp4
still $W/clean.mp4 31.75 $W/k3.png

clip() { # src start end out [speed]
  local sp=${5:-1}
  ffmpeg -y -loglevel error -ss "$2" -to "$3" -i "$1" -vf "setpts=(PTS-STARTPTS)/$sp,fps=$FPS,format=yuv420p" \
    -c:v libx264 -crf 16 -an "$4"
}
box() { echo "drawbox=x=$1:y=$2:w=$3:h=$4:color=$ORANGE@0.13:t=fill,drawbox=x=$1:y=$2:w=$3:h=$4:color=$ORANGE:t=6"; }
hold() { # still dur cx cy Z boxes out  (zoom eases from 1 to Z in 0.8 s, then creeps 4 % more)
  local n; n=$(python3 -c "print(round($2*$FPS))")
  local z="1+($5-1)*(1-cos(PI*min(1,on/20)))/2+0.04*on/$n"
  ffmpeg -y -loglevel error -loop 1 -framerate $FPS -t "$2" -i "$1" -vf \
    "$6,scale=3840:2160,zoompan=z='$z':x='max(0,min(iw-iw/zoom,$3*2-iw/zoom/2))':y='max(0,min(ih-ih/zoom,$4*2-ih/zoom/2))':d=1:s=1920x1080:fps=$FPS,format=yuv420p" \
    -frames:v "$n" -c:v libx264 -crf 16 "$7"
}

# 2. Scenes.
clip $W/blurred.mp4 3.0 4.95 $W/s1a.mp4
hold $W/k0.png 4.55 760 525 1.8 "$(box 655 504 405 42)" $W/s1b.mp4                      # €138.55 from 1 Nov
clip $W/blurred.mp4 4.95 8.80 $W/s2a.mp4
hold $W/k1.png 3.95 510 595 1.6 "$(box 90 563 842 61)" $W/s2b.mp4                       # 51 days vs 90 days
clip $W/blurred.mp4 8.80 12.25 $W/s3a.mp4
hold $W/k2.png 5.70 500 640 1.4 "$(box 420 414 304 33),$(box 270 832 307 36)" $W/s3b.mp4 # fair point + VERIFIED
clip $W/blurred.mp4 12.25 30.0 $W/s4.mp4 6                                              # rounds 2-4, fast
clip $W/blurred.mp4 30.0 31.75 $W/s5a.mp4
hold $W/k3.png 5.00 546 760 1.55 "$(box 66 912 960 60)" $W/s5b.mp4                      # we accept €132.85
hold $W/k3.png 3.00 1505 330 1.9 "$(box 1158 248 196 80),$(box 1626 300 228 30)" $W/s6.mp4 # 0.97, −€55,339

printf "file '%s'\n" s1a.mp4 s1b.mp4 s2a.mp4 s2b.mp4 s3a.mp4 s3b.mp4 s4.mp4 s5a.mp4 s5b.mp4 s6.mp4 > $W/list.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i $W/list.txt -c copy $W/video.mp4

# 3. Voices: placed on the scene starts, then cleaned up (high-pass, compression, loudness).
dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
T=$(python3 - "$W" <<'EOF'
import subprocess, sys
w = sys.argv[1]
d = lambda f: float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f"{w}/{f}"]))
s1 = 0; s2 = s1 + d("s1a.mp4") + d("s1b.mp4"); s3 = s2 + d("s2a.mp4") + d("s2b.mp4")
s5 = s3 + d("s3a.mp4") + d("s3b.mp4") + d("s4.mp4")
ms = lambda t: int(t * 1000)
print(ms(s1 + .2), ms(s2 + .2), ms(s3 + .3), ms(s3 + 2.7), ms(s5 + .2))
EOF
)
read A1 A2 A3 A4 A5 <<< "$T"
ffmpeg -y -loglevel error -i $W/video.mp4 \
  -i $V/v1_owner_offer.mp3 -i $V/v2_buyer_notice.mp3 -i $V/v3_backoffice_counter.mp3 \
  -i $V/v4_owner_fairpoint.mp3 -i $V/v6_owner_accept.mp3 -filter_complex "
[1:a]adelay=$A1|$A1[a1];[2:a]adelay=$A2|$A2[a2];[3:a]volume=1.6,adelay=$A3|$A3[a3];
[4:a]adelay=$A4|$A4[a4];[5:a]adelay=$A5|$A5[a5];
[a1][a2][a3][a4][a5]amix=inputs=5:normalize=0:duration=longest,
highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=120:makeup=4,
loudnorm=I=-15:TP=-1.5:LRA=7,apad[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -ar 48000 -shortest renders/middle_v2.mp4
dur renders/middle_v2.mp4
