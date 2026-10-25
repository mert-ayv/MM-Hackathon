#!/usr/bin/env bash
# Experiment: the demo video at 1.25x, plus a ~12 s "how it wins" segment over the Tactopus Agent Studio
# (narrated by a third AI voice) between the result card and Ege's outro.
# Needs: renders/final/*.mp4 (build_final.sh), renders/studio/studio.png (build_studio_cutaway.sh),
# source/voices/v2/fast/v9_studio.wav (studio narration), source/music_bed.mp3.
set -euo pipefail
cd "$(dirname "$0")"
W=renders/fast
mkdir -p $W
FPS=25
SP=1.25

# 1. All parts at 1.25x (picture and voice).
for p in a1 a2 a3 a4 a5 b1 c1 c3 c4 c5 d1; do
  ffmpeg -y -loglevel error -i renders/final/$p.mp4 -filter_complex \
    "[0:v]setpts=PTS/$SP,fps=$FPS[v];[0:a]atempo=$SP,aresample=48000,aformat=channel_layouts=stereo[a]" \
    -map "[v]" -map "[a]" -c:v libx264 -crf 17 -pix_fmt yuv420p -c:a aac -b:a 192k $W/$p.mp4
done

# 2. Studio segment: four zooms on the Agent Studio diagram, timed to the narration (STUDIO_CUTS: seconds
# where shots 2-4 start), with orange boxes on the nodes being talked about.
ORANGE=0xF2552C
box() { echo "drawbox=x=$1:y=$2:w=$3:h=$4:color=$ORANGE@0.12:t=fill,drawbox=x=$1:y=$2:w=$3:h=$4:color=$ORANGE:t=6"; }
hold() { # still dur cx cy Z boxes out
  local n; n=$(python3 -c "print(round($2*$FPS))")
  local z="$5*(0.9+0.1*(1-cos(PI*min(1,on/18)))/2)+0.03*on/$n"   # starts close (no zoom-out pumping between shots)
  ffmpeg -y -loglevel error -loop 1 -framerate $FPS -t "$2" -i "$1" -vf \
    "$6,scale=3840:2160,zoompan=z='$z':x='max(0,min(iw-iw/zoom,$3*2-iw/zoom/2))':y='max(0,min(ih-ih/zoom,$4*2-ih/zoom/2))':d=1:s=1920x1080:fps=$FPS,format=yuv420p" \
    -frames:v "$n" -c:v libx264 -crf 16 "$7"
}
NARR=source/voices/v2/fast/v9_studio.wav
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $NARR)
read C1 C2 C3 <<< "${STUDIO_CUTS:-5.8 8.05 9.35}"
T=$(python3 -c "print(round($D+0.6,2))")
d() { python3 -c "print(round($1,2))"; }
P=renders/studio/studio.png
hold $P $C1 940 255 1.7 "$(box 823 182 230 150)" $W/st1.mp4                                       # dossier
hold $P $(d "$C2-$C1") 1240 250 1.7 "$(box 1124 182 230 136)" $W/st2.mp4                          # evidence & claims
hold $P $(d "$C3-$C2") 460 600 1.5 "$(box 188 524 232 150),$(box 500 524 232 172)" $W/st3.mp4      # lever engine + concession planner
hold $P $(d "$T-$C3") 1240 740 1.5 "$(box 1124 524 232 150),$(box 1124 838 232 150)" $W/st4.mp4   # guardrail + deal
printf "file '%s'\n" st1.mp4 st2.mp4 st3.mp4 st4.mp4 > $W/st.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i $W/st.txt -i $NARR -filter_complex \
  "[1:a]adelay=200|200,highpass=f=80,acompressor=threshold=-20dB:ratio=3:makeup=4,aresample=48000,aformat=channel_layouts=stereo,apad[a]" \
  -map 0:v -map "[a]" -shortest -c:v libx264 -crf 17 -c:a aac -b:a 192k $W/st.mp4

# 3. Join, music bed (ducked), loudness.
PARTS="a1 a2 a3 a4 a5 b1 st c1 c3 c4 c5 d1"
IN=""; F=""; i=0
for p in $PARTS; do IN="$IN -i $W/$p.mp4"; F="$F[$i:v][$i:a]"; i=$((i+1)); done
FADE=$(for p in $PARTS; do ffprobe -v error -show_entries format=duration -of csv=p=0 $W/$p.mp4; done | python3 -c "import sys; print(round(sum(map(float, sys.stdin)) - 1.2, 2))")
ffmpeg -y -loglevel error $IN -i source/music_bed.mp3 -filter_complex "${F}concat=n=$i:v=1:a=1[v][a0];
  [a0]asplit[voice][key];
  [$i:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.22,afade=t=in:d=0.6,apad[m0];
  [m0][key]sidechaincompress=threshold=0.03:ratio=4:attack=30:release=400[m1];
  [voice][m1]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=8,afade=t=out:st=$FADE:d=1.2[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -r $FPS -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart $W/nosubs.mp4

# 4. Captions: the normal ones retimed (/1.25, shifted after the studio segment) plus the narration's.
A_END=$(for p in a1 a2 a3 a4 a5 b1; do ffprobe -v error -show_entries format=duration -of csv=p=0 $W/$p.mp4; done | python3 -c "import sys; print(sum(map(float, sys.stdin)))")
ST=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $W/st.mp4)
STUDIO_CAPS='[[0.2,2.8,"Before the first email, our agent knows the supplier:"],[2.9,5.6,"its costs, its contract, its hedges."],[5.85,7.85,"It argues only with verified facts,"],[8.05,9.25,"code sets every price,"],[9.35,11.3,"and it never signs worse than our fallback."]]' CAPS_FAST=1 A_END=$A_END ST_LEN=$ST SPEED=$SP uv run --no-project --with playwright python make_captions.py $W/captions
CIN=""; while read -r f; do CIN="$CIN -i $f"; done < $W/captions/inputs.txt
ffmpeg -y -loglevel error -i $W/nosubs.mp4 $CIN -/filter_complex $W/captions/filter.txt \
  -map "[vout]" -map 0:a -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -c:a copy -movflags +faststart \
  renders/csee-base-demo-fast.mp4
ffprobe -v error -show_entries format=duration -of csv=p=0 renders/csee-base-demo-fast.mp4
