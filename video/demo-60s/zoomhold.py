"""Smooth zoom on a still image: subpixel affine transform per frame (Pillow, bicubic), piped to ffmpeg.
ffmpeg's zoompan rounds the crop position to whole pixels, which makes slow zooms judder.

usage: zoomhold.py still.png seconds cx cy Z curve out.mp4
  cx, cy: zoom centre in 1920x1080 image pixels; Z: target zoom
  curve "ease": 1 -> Z over 0.8 s, then creeps 4 % more (middle part)
  curve "close": starts at 0.9 Z, eases to Z, creeps 3 % (studio shots, no zoom-out between cuts)
"""
import math
import subprocess
import sys
from PIL import Image

src, dur, cx, cy, Z, curve, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), \
    float(sys.argv[5]), sys.argv[6], sys.argv[7]
FPS, W, H = 25, 1920, 1080
img = Image.open(src).convert("RGB").resize((W, H), Image.LANCZOS)
n = round(dur * FPS)


def zoom(i):
    ease = (1 - math.cos(math.pi * min(1.0, i / (20 if curve == "ease" else 18)))) / 2
    if curve == "ease":
        return 1 + (Z - 1) * ease + 0.04 * i / n
    return Z * (0.9 + 0.1 * ease) + 0.03 * i / n


ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                       "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", out],
                      stdin=subprocess.PIPE)
for i in range(n):
    z = zoom(i)
    vw, vh = W / z, H / z                                   # visible window in source pixels (float)
    x0 = min(max(cx - vw / 2, 0), W - vw)
    y0 = min(max(cy - vh / 2, 0), H - vh)
    # affine map output (u, v) -> source (x0 + u/z, y0 + v/z), subpixel exact
    frame = img.transform((W, H), Image.AFFINE, (1 / z, 0, x0, 0, 1 / z, y0), resample=Image.BICUBIC)
    ff.stdin.write(frame.tobytes())
ff.stdin.close()
sys.exit(ff.wait())
