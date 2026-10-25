#!/usr/bin/env bash
# Final 60 s demo video, YC-launch style: presenter takes (front/side angles, punch-in, jump cuts),
# a text match cut, the dashboard middle part, the Agent Studio cutaway, stat cards and an end card.
# Inputs: source/takes/IMG_79xx.MOV (Mert intro, Ege outro), renders/matchcut/mc_*.png (make_matchcut.py),
# renders/middle_v5.mp4, renders/overlays/*.png (make_overlays.py).
set -euo pipefail
cd "$(dirname "$0")"
T=source/takes
O=renders/overlays
W=renders/final
mkdir -p $W
FPS=25
AFX="highpass=f=90,afftdn=nf=-25,acompressor=threshold=-22dB:ratio=3:attack=5:release=150:makeup=5,aresample=48000,aformat=channel_layouts=stereo"
# Presenter voices: ElevenLabs Voice Isolator output (source/iso/<take>_iso.mp3, cut from <take> at iso_off) +
# a gentle EQ (less boxiness, more presence and air) so they sit next to the AI voices.
VFX="highpass=f=80,equalizer=f=220:t=o:w=1:g=-2.5,equalizer=f=3500:t=o:w=1.2:g=2.5,equalizer=f=10000:t=o:w=1:g=1.5,acompressor=threshold=-22dB:ratio=3:attack=5:release=150:makeup=4,aresample=48000,aformat=channel_layouts=stereo"
iso_off() { case $1 in IMG_7967) echo 0.5;; IMG_7972) echo 8.4;; IMG_7969) echo 28.7;; IMG_7970) echo 4.2;; IMG_7971) echo 12.1;; esac; }

take() { # src start end face_x face_y zoom out [overlay filter chain on [v]]
  local src=$1 s=$2 e=$3 fx=$4 fy=$5 z=$6 out=$7 ov=${8:-}
  local vf="[0:v]crop=iw/$z:ih/$z:'max(0,min(iw-iw/$z,iw*$fx-iw/$z/2))':'max(0,min(ih-ih/$z,ih*$fy-ih/$z*0.4))',scale=1920:1080,fps=$FPS,setsar=1[v]"
  local d; d=$(python3 -c "print(round($e-$s,3))")
  local L="-loop 1 -framerate $FPS -t $d -i"
  local tk; tk=$(basename "$src" .MOV); local off; off=$(iso_off "$tk")
  local as ae; as=$(python3 -c "print(round($s-$off,3))"); ae=$(python3 -c "print(round($e-$off,3))")
  ffmpeg -y -loglevel error -ss "$s" -to "$e" -i "$src" $L $O/card_95.png $L $O/card_deals.png $L $O/card_77.png \
    $L $O/card_70.png $L $O/name_mert.png $L $O/name_ege.png -ss "$as" -to "$ae" -i source/iso/${tk}_iso.mp3 \
    -filter_complex "$vf;${ov:-[v]null[vo]};[7:a]$VFX[a]" -map "[vo]" -map "[a]" \
    -c:v libx264 -crf 17 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest "$out"
}
# overlay input numbers in take(): 1 card_95, 2 card_deals, 3 card_77, 4 card_70, 5 name_mert, 6 name_ege
pop() { echo "[$1:v]format=rgba,fade=in:st=$2:d=0.2:alpha=1[o$1]"; }

# 1. Intro. A text match cut on its own (make_matchcut.py: "price increase" in a dozen procurement documents,
# always at the frame centre, cuts speeding up, last frame the Brandlhuber letter), then Mert's front take
# with the whole first line; "+9.5 %" pops on "nine".
MC=renders/matchcut
FR=(4 4 4 3 3 3 3 3 2 2 2 2 14)   # frames per document at 25 fps -> 1.96 s
: > $MC/list.txt; i=0; CLICKS=""; t=0
for f in "${FR[@]}"; do
  printf "file 'mc_%02d.png'\nduration %s\n" $i "$(python3 -c "print($f/$FPS)")" >> $MC/list.txt
  CLICKS="$CLICKS $t"; t=$(python3 -c "print(round($t+$f/$FPS,3))"); i=$((i+1))
done
printf "file 'mc_12.png'\n" >> $MC/list.txt
python3 - $MC/clicks.wav 1.96 $CLICKS <<'PY'   # a short paper click at every cut
import math, random, struct, sys, wave
out, dur, cuts = sys.argv[1], float(sys.argv[2]), [float(x) for x in sys.argv[3:]]
sr = 48000
buf = [0.0] * int(sr * dur)
for c in cuts:
    for i in range(int(sr * 0.03)):
        j = int(c * sr) + i
        if j < len(buf):
            buf[j] += 0.5 * random.uniform(-1, 1) * math.exp(-i / sr * 180)
w = wave.open(out, "wb")
w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 32767)) for v in buf))
w.close()
PY
ffmpeg -y -loglevel error -f concat -safe 0 -i $MC/list.txt -i $MC/clicks.wav -filter_complex \
  "[0:v]fps=$FPS,scale=3840:2160,zoompan=z='1+0.0016*on':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=$FPS,setsar=1,format=yuv420p[v];
   [1:a]highpass=f=1500,volume=0.35,aresample=48000,aformat=channel_layouts=stereo[a]" \
  -map "[v]" -map "[a]" -t 1.96 -c:v libx264 -crf 17 -c:a aac -b:a 192k $W/a1.mp4
take $T/IMG_7967.MOV 0.75 6.15 0.51 0.35 1.2 $W/a2.mp4 \
  "$(pop 1 3.95);$(pop 5 0);[v][o5]overlay=enable='lt(t,2.6)'[v1];[v1][o1]overlay=enable='gte(t,3.95)'[vo]"
# Line 2 from the side angle, pauses cut out (jump cuts).
take $T/IMG_7972.MOV 8.62 10.62 0.51 0.37 1.35 $W/a3.mp4
take $T/IMG_7972.MOV 11.08 14.12 0.51 0.37 1.45 $W/a4.mp4
take $T/IMG_7972.MOV 14.52 15.55 0.51 0.37 1.35 $W/a5.mp4

# 2. Middle: dashboard replay, voices, zooms (build_middle_v5.sh).
cp renders/middle_v5.mp4 $W/b1.mp4

# 3. Outro (Ege). "Code sets every number…" on camera (the Agent Studio stays for the technical video and the pitch).
take $T/IMG_7969.MOV 28.95 33.85 0.52 0.44 1.2 $W/c1.mp4 "$(pop 6 0);[v][o6]overlay=enable='lt(t,2.8)'[vo]"
take $T/IMG_7970.MOV 4.45 8.62 0.53 0.40 1.2 $W/c3.mp4 \
  "$(pop 2 0.1);$(pop 3 1.8);[v][o2]overlay=enable='gte(t,0.1)'[v2];[v2][o3]overlay=enable='gte(t,1.8)'[vo]"
take $T/IMG_7971.MOV 15.0 16.62 0.56 0.28 1.35 $W/c4.mp4 "$(pop 4 0.05);[v][o4]overlay[vo]"
take $T/IMG_7970.MOV 11.35 12.5 0.53 0.40 1.3 $W/c5.mp4
ffmpeg -y -loglevel error -loop 1 -framerate $FPS -t 1.0 -i $O/endcard.png -f lavfi -t 1.0 -i anullsrc=r=48000:cl=stereo \
  -vf "fade=in:st=0:d=0.25,format=yuv420p" -c:v libx264 -crf 17 -c:a aac -b:a 192k -shortest $W/d1.mp4

# 4. Join everything and level the whole mix.
PARTS="a1 a2 a3 a4 a5 b1 c1 c3 c4 c5 d1"
IN=""; F=""; i=0
for p in $PARTS; do IN="$IN -i $W/$p.mp4"; F="$F[$i:v][$i:a]"; i=$((i+1)); done
# Light music bed (ElevenLabs Music, source/music_bed.mp3) under everything, ducked under speech.
MUSIC=source/music_bed.mp3
FADE=$(for p in $PARTS; do ffprobe -v error -show_entries format=duration -of csv=p=0 $W/$p.mp4; done | python3 -c "import sys; print(round(sum(map(float, sys.stdin)) - 1.2, 2))")
ffmpeg -y -loglevel error $IN -i $MUSIC -filter_complex "${F}concat=n=$i:v=1:a=1[v][a0];
  [a0]asplit[voice][key];
  [$i:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.22,afade=t=in:d=0.6,apad[m0];
  [m0][key]sidechaincompress=threshold=0.03:ratio=4:attack=30:release=400[m1];
  [voice][m1]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=8,
  afade=t=out:st=$FADE:d=1.2[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -r $FPS -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart renders/csee-base-demo-nosubs.mp4

# 5. Burned-in captions (make_captions.py: one PNG per caption, timed overlays).
uv run --no-project --with playwright python make_captions.py renders/captions
CIN=""; while read -r f; do CIN="$CIN -i $f"; done < renders/captions/inputs.txt
ffmpeg -y -loglevel error -i renders/csee-base-demo-nosubs.mp4 $CIN -/filter_complex renders/captions/filter.txt \
  -map "[vout]" -map 0:a -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -c:a copy -movflags +faststart \
  renders/csee-base-demo.mp4
ffprobe -v error -show_entries format=duration:stream=width,height,r_frame_rate -of compact renders/csee-base-demo.mp4
