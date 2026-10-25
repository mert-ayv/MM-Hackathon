#!/usr/bin/env bash
# Final 60 s demo video, YC-launch style: presenter takes (front/side angles, punch-in, jump cuts),
# Higgsfield foundry B-roll, the dashboard middle part, the Agent Studio cutaway, stat cards and an end card.
# Inputs: source/takes/IMG_79xx.MOV (Mert intro, Ege outro), source/foundry_higgsfield.mp4,
# renders/middle_v4.mp4, renders/overlays/*.png (make_overlays.py).
set -euo pipefail
cd "$(dirname "$0")"
T=source/takes
O=renders/overlays
W=renders/final
mkdir -p $W
FPS=25
AFX="highpass=f=90,afftdn=nf=-25,acompressor=threshold=-22dB:ratio=3:attack=5:release=150:makeup=5,aresample=48000,aformat=channel_layouts=stereo"

take() { # src start end face_x face_y zoom out [overlay filter chain on [v]]
  local src=$1 s=$2 e=$3 fx=$4 fy=$5 z=$6 out=$7 ov=${8:-}
  local vf="[0:v]crop=iw/$z:ih/$z:'max(0,min(iw-iw/$z,iw*$fx-iw/$z/2))':'max(0,min(ih-ih/$z,ih*$fy-ih/$z*0.4))',scale=1920:1080,fps=$FPS,setsar=1[v]"
  local d; d=$(python3 -c "print(round($e-$s,3))")
  local L="-loop 1 -framerate $FPS -t $d -i"
  ffmpeg -y -loglevel error -ss "$s" -to "$e" -i "$src" $L $O/card_95.png $L $O/card_deals.png $L $O/card_77.png \
    $L $O/card_70.png $L $O/name_mert.png $L $O/name_ege.png \
    -filter_complex "$vf;${ov:-[v]null[vo]};[0:a]$AFX[a]" -map "[vo]" -map "[a]" \
    -c:v libx264 -crf 17 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest "$out"
}
# overlay input numbers in take(): 1 card_95, 2 card_deals, 3 card_77, 4 card_70, 5 name_mert, 6 name_ege
pop() { echo "[$1:v]format=rgba,fade=in:st=$2:d=0.2:alpha=1[o$1]"; }

# 1. Intro (Mert). Line 1 starts over the foundry shot, then his front take; "+9.5 %" pops on "nine".
ffmpeg -y -loglevel error -i source/foundry_higgsfield.mp4 -ss 0.75 -to 3.45 -i $T/IMG_7967.MOV -filter_complex \
  "[0:v]trim=0:2.7,setpts=PTS-STARTPTS,scale=1920:1080,fps=$FPS,setsar=1,format=yuv420p[v];[1:a]$AFX[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -crf 17 -c:a aac -b:a 192k -shortest $W/a1.mp4
take $T/IMG_7967.MOV 3.45 6.15 0.51 0.35 1.2 $W/a2.mp4 \
  "$(pop 1 1.2);$(pop 5 0);[v][o5]overlay=enable='lt(t,2.4)'[v1];[v1][o1]overlay=enable='gte(t,1.2)'[vo]"
# Line 2 from the side angle, pauses cut out (jump cuts).
take $T/IMG_7972.MOV 8.62 10.62 0.51 0.37 1.35 $W/a3.mp4
take $T/IMG_7972.MOV 11.08 14.12 0.51 0.37 1.45 $W/a4.mp4
take $T/IMG_7972.MOV 14.52 15.55 0.51 0.37 1.35 $W/a5.mp4

# 2. Middle: dashboard replay, voices, zooms (build_middle_v4.sh).
cp renders/middle_v4.mp4 $W/b1.mp4

# 3. Outro (Ege). "Code sets every number…" on camera (the Agent Studio stays for the technical video and the pitch).
take $T/IMG_7969.MOV 28.95 33.85 0.52 0.44 1.2 $W/c1.mp4
take $T/IMG_7970.MOV 4.45 8.62 0.53 0.40 1.2 $W/c3.mp4 \
  "$(pop 2 0.1);$(pop 3 1.8);$(pop 6 0);[v][o6]overlay=enable='lt(t,2.6)'[v1];[v1][o2]overlay=enable='gte(t,0.1)'[v2];[v2][o3]overlay=enable='gte(t,1.8)'[vo]"
take $T/IMG_7971.MOV 15.0 16.62 0.56 0.28 1.35 $W/c4.mp4 "$(pop 4 0.05);[v][o4]overlay[vo]"
take $T/IMG_7970.MOV 11.35 12.5 0.53 0.40 1.3 $W/c5.mp4
ffmpeg -y -loglevel error -loop 1 -framerate $FPS -t 1.0 -i $O/endcard.png -f lavfi -t 1.0 -i anullsrc=r=48000:cl=stereo \
  -vf "fade=in:st=0:d=0.25,format=yuv420p" -c:v libx264 -crf 17 -c:a aac -b:a 192k -shortest $W/d1.mp4

# 4. Join everything and level the whole mix.
PARTS="a1 a2 a3 a4 a5 b1 c1 c3 c4 c5 d1"
IN=""; F=""; i=0
for p in $PARTS; do IN="$IN -i $W/$p.mp4"; F="$F[$i:v][$i:a]"; i=$((i+1)); done
ffmpeg -y -loglevel error $IN -filter_complex "${F}concat=n=$i:v=1:a=1[v][a0];[a0]loudnorm=I=-14:TP=-1.5:LRA=8[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -r $FPS -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart renders/csee-base-demo.mp4
ffprobe -v error -show_entries format=duration:stream=width,height,r_frame_rate -of compact renders/csee-base-demo.mp4
