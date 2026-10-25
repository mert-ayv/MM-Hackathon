# Narration cue sheet (technical video, 60 s)

**Done (Sun 11:40): `tech-60s_v1_elevenlabs.mp4`** = the Claude Motion master + ElevenLabs narration (voice
"Artaius, Calm British Narrator", model eleven_v4, nine clips on flow `SiYdq5NFhjd2HYwTDuyt`, clips in
`narration/`, placement in `narration/layout.txt`). The voice reads at about 2.2 words/s, slower than the
script's 2.6, so three lines were shortened and all clips run at tempo 1.11. Lines as recorded:

| Start (s) | Line as voiced |
|---|---|
| 0.5 | Supplier bots, one minute per thread, scored on total cost. Our rule: |
| 6.3 | Code decides every number. The language model only reads and writes. |
| 11.1 | Offline, a dossier on all forty-six suppliers. Every cited ID is checked by code. |
| 17.5 | An engine prices every term with the arena's exact cost model. |
| 21.5 | A policy anchors, paces the concessions, and sends up to three term sheets per e-mail. |
| 27.5 | Claude words the reply in the supplier's register. Numbers and claim sentences stay verbatim. |
| 34.5 | From two hundred and sixty of our own sessions we fitted the bots: tit-for-tat, a shrinking cap, fixed patience. So we concede exactly what they will mirror, and never push after a final offer. |
| 46.6 | Every change climbed one ladder: simulator, sandbox, one practice run. A router picks the measured winner per case type. An LLM choosing the moves scored worse. |
| 57.9 | Code checks every euro. |

Clip 7 starts 2 s before its chart on purpose (voice leads picture over the silent guardrails band). If a human
reads it instead (Route A), use the original lines below; a person at 2.6 words/s fits them.

Both masters are silent: `tech-60s_motion_v1_silent.mp4` (Claude Motion, footer removed) and
`tech-60s_v1_silent.mp4` (local build). Original cue sheet, 158 words at 2.6 words/s:

| Cue (s) | Line |
|---|---|
| 0.5 | One to three supplier bots, a sixty-second clock per thread, scored on total cost. Our rule: |
| 6.3 | Code decides every number. The language model only reads and writes. |
| 10.5 | Offline, a dossier on all forty-six suppliers. Every cited ID is checked by code. |
| 15.5 | An engine prices every term with the arena's exact cost model. |
| 20.5 | A policy anchors, paces the concessions and sends up to three term sheets per e-mail. |
| 27.5 | Claude words the reply in the supplier's register. Numbers and claim sentences stay verbatim. |
| 33.0 | (silence, guardrails band) |
| 36.5 | From two hundred sixty of our own sessions we fitted the bots: tit-for-tat, a shrinking cap, fixed patience. So we concede exactly what they will mirror, and never push after a final offer. |
| 47.3 | Every change climbed one ladder: simulator, sandbox, one logged practice run. The ledger holds hundreds of logged runs, and a router sends each case type to its measured winner. An LLM choosing the moves scored worse, so it doesn't. |
| 56.5 | csee-base. Code checks every euro. |

## Route A: one of us reads it (recommended)

Same presenter voice as the demo video, which the jury will see right before this one. Record the table
top to bottom in one take, pausing at the cue times (a phone voice memo is fine; quiet room, 30 cm from the mic).
Then:

```bash
ffmpeg -i tech-60s_motion_v1_silent.mp4 -i narration.m4a -c:v copy -c:a aac -b:a 192k -shortest tech-60s_v1.mp4
```

If the take drifts from the cues, trim the start with `-ss` on the audio input, or record scene by scene and
place each clip at its cue with `adelay` (see Route B).

## Route B: ElevenLabs text-to-speech

One command, once `ELEVENLABS_API_KEY=` is added to `starter-kit/.env` (key from elevenlabs.io → profile → API keys):

```bash
cd starter-kit
uv run --with requests python ../video/tech-60s/build/narrate.py --list-voices          # pick a calm neutral English voice
uv run --with requests python ../video/tech-60s/build/narrate.py --voice Daniel         # 9 clips → narration/, muxed → tech-60s_v1_elevenlabs.mp4
```

It warns if a clip would run into the next cue (then `--speed 1.1`). Manual alternative via the web app: Generate **one clip
per row** of the table, same voice, speed 1.0, and save them as `n01.mp3` … `n09.mp3` in a folder `narration/`.
Pick a calm, neutral English voice; not the German owner voice from the demo, that one belongs to the supplier.
Then place each clip at its cue (milliseconds) and mux:

```bash
ffmpeg -i tech-60s_motion_v1_silent.mp4 \
  -i narration/n01.mp3 -i narration/n02.mp3 -i narration/n03.mp3 -i narration/n04.mp3 -i narration/n05.mp3 \
  -i narration/n06.mp3 -i narration/n07.mp3 -i narration/n08.mp3 -i narration/n09.mp3 \
  -filter_complex "[1]adelay=500|500[a1];[2]adelay=6300|6300[a2];[3]adelay=10500|10500[a3];[4]adelay=15500|15500[a4];\
[5]adelay=20500|20500[a5];[6]adelay=27500|27500[a6];[7]adelay=36500|36500[a7];[8]adelay=47300|47300[a8];\
[9]adelay=56500|56500[a9];[a1][a2][a3][a4][a5][a6][a7][a8][a9]amix=inputs=9:normalize=0[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest tech-60s_v1.mp4
```

Check that no clip runs into the next cue (row 8 has 10.8 s, row 9 has 9.2 s; at 2.6 words/s both fit).
Either route: play the result once end to end before uploading.
