# Video-engine benchmark protocol

Three Reason Sessions implement [SCRIPT.md](SCRIPT.md) at the same time, one engine
each: **Remotion 4**, **HyperFrames** (heygen-com/hyperframes) and **FFrames 1.2**
(dmtrKovalenko/fframes). The goal is a polished, publishable-quality first cut with
very little iteration, and a fair measure of how long each engine takes to get there.

## Held constant

| | |
| --- | --- |
| Script | [SCRIPT.md](SCRIPT.md), unchanged |
| Audio | `python3 make_score.py soundtrack.wav`; sha256 starts `2d8fe2ed7846a00d` |
| Output | 1920x1080, 60 fps, 3600 frames, 60.000 s, H.264 yuv420p (CRF 18 or better), AAC 48 kHz stereo |
| Machine | Reason cloud `compute-linux-l` (4 vCPU, 8 GB), no GPU assumed |
| Model | Organization default model, reasoning effort `high` |
| Repo | `reason-machines/content-factory`, new folder `bench/<engine>/` only |
| Assets | Copy what you need from content-factory `public/` (fonts, marks, marble, avatars) into your folder |

## Rules

1. **Fresh build.** Write the composition from scratch in `bench/<engine>/`. You may
   read existing content-factory code for geometry and tokens, but do not import or copy
   code from `src/` or `fframes/*/src`. Do not edit anything outside your folder.
2. **Use the engine's own path.** Follow its official docs and agent skill (Remotion:
   remotion.dev docs; HyperFrames: its README, docs and `skills/`; FFrames:
   `npx skills add https://fframes.studio` or the repo's `skills/fframes-video`). Do not
   switch engines or pre-render scenes with another engine; if the engine cannot do
   something, say so.
3. **Light iteration.** Build every scene, render, then at most **two review passes**
   (look at stills and a contact sheet, fix what is clearly wrong, re-render). Aim for
   about 60 minutes wall clock; stop at 90 and deliver what you have.
4. **Timing log.** Record UTC timestamps for: start, engine installed and a hello-world
   frame rendered, first full-length render, final render. Time the final full render
   command with `time` and note `nproc`.
5. **Verify.** `ffprobe` the final MP4 (size, fps, frame count, duration, audio). Extract
   stills at 2.0, 8, 17, 26, 34, 42, 50 and 57.5 s and look at every one. Make a contact
   sheet at 1 fps (`tile=6x10`).
6. **Deliver.** Commit `bench/<engine>/` (sources, no MP4) to your session branch and
   open a **draft** pull request on content-factory; do not merge it. Publish the final
   MP4 and the contact sheet with `tools.media_publish_file` and put the returned
   Markdown in your final reply. No social posting.

## Final reply (exact fields)

```
engine / version:
timestamps (UTC): start | engine ready | first full render | final render
final render wall time (s), nproc:
review passes used (0-2):
ffprobe: WxH, fps, frames, duration, audio
script deviations (scene by scene, honest):
engine friction (what was hard or impossible):
video: <media markdown>
contact sheet: <media markdown>
draft PR:
```
