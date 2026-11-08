"""Mix a one-take voice-over onto the rendered video (video stream copied, no re-encode).

Usage: python video/scripts/mix-voiceover.py [vo.mp3] [video.mp4] [out.mp4]
vo-bounds.json = the 10 chapter boundaries (seconds) of the voice file, found by aligning the script words
(docs/VOICEOVER.md) to the detected speech segments. Each chapter is placed at its video slot start plus a short lead-in.
"""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FF = ROOT / "video/node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe"
SLOT_START = [0, 12, 35, 85, 105, 130, 150, 170, 195]  # docs/VIDEO.md chapter starts (s)
LEAD = 0.3
vo = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "video/audio/vo.mp3"
video = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "video-out/actionproof-demo.mp4"
out = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "video-out/actionproof-demo-voiced.mp4"
b = json.loads((ROOT / "video/data/vo-bounds.json").read_text())
assert len(b) == len(SLOT_START) + 1
n = len(SLOT_START)
ends = SLOT_START[1:] + [205.06]
chain, labels = [], []
sil = LEAD
chain.append(f"anullsrc=r=44100:cl=mono,atrim=0:{sil:.3f}[s0]"); labels.append("[s0]")
for i in range(n):
    dur = b[i + 1] - b[i]
    slot = ends[i] - SLOT_START[i]
    assert LEAD + dur <= slot + 0.01, f"chapter {i+1} voice ({dur:.1f}s) does not fit its slot ({slot:.1f}s)"
    chain.append(f"[{i+1}:a]atrim={b[i]:.3f}:{b[i+1]:.3f},asetpts=PTS-STARTPTS,aresample=44100[c{i}]"); labels.append(f"[c{i}]")
    if i + 1 < n:
        gap = slot - dur  # next chapter starts exactly at its slot start + LEAD
        chain.append(f"anullsrc=r=44100:cl=mono,atrim=0:{gap:.3f}[s{i+1}]"); labels.append(f"[s{i+1}]")
fc = ";".join(chain) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1,loudnorm=I=-16:TP=-1.5:LRA=11,apad[aout]"
inputs = ["-i", str(video)] + sum((["-i", str(vo)] for _ in range(n)), [])
cmd = [str(FF), "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", fc,
       "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-t", "205.06", str(out)]
subprocess.run(cmd, check=True)
print("wrote", out)
