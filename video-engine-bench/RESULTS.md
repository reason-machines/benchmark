# Results

Runs started 17:52 UTC on identical 4-core cloud machines, same script,
protocol and soundtrack. Times are as reported by each run.

## Remotion 4 (finished)

| Field | Value |
| --- | --- |
| Session | https://reasonmachines.com/agents/3d43b76b-ff23-433e-b808-e63e1cfd898d |
| Draft PR | https://github.com/reason-machines/content-factory/pull/6 (not merged) |
| Engine | Remotion 4.0.536, React 19.2, bun 1.3.14, system Chromium |
| Start | 17:52:41 |
| Engine ready (hello-world still) | 17:54:27 (+1m46s) |
| First full render done | 18:13:05 (+20m24s) |
| Final render done | 18:19:21 (+26m40s) |
| Final render wall time | 323.9 s at `--concurrency=4` (~11 fps) |
| Review passes | 2 of 2 |
| Output | 1920x1080, 60 fps, 3600 frames, H.264 High yuv420p CRF 18, AAC 48 kHz; soundtrack hash verified |

**Deviations:** small, mostly added chrome (Slack workspace UI, window titles, a tax row so
totals add up), invented filler text for sub-agent lines and line items, a zoom instead of a
pan in the hook. All scripted copy is exact.

**Engine friction:** headless-shell download blocked by the sandbox proxy (used system
Chromium); Chrome "socket path too long" under the long session TMPDIR; JPEG frames
defaulted to yuvj420p until `Config.setColorSpace("bt709")`; CPU-only rendering at ~11 fps.
Nothing in the script was impossible.

**Video:** not published. `media_publish_file` rejected every video file on that machine
(including a 2 s ffmpeg test pattern), so this is a publishing-tool problem, not a render
problem. Quality is judged from the contact sheet and protocol stills:

![Remotion 4 contact sheet, 1 fps](https://api.reasonmachines.com/media/pr-screenshots/3d43b76b-ff23-433e-b808-e63e1cfd898d/ae6bf487b7f64348bff03e206eef5242/contact.png)

![Remotion 4 protocol stills at 2, 8, 17, 26, 34, 42, 50, 57.5 s](https://api.reasonmachines.com/media/pr-screenshots/3d43b76b-ff23-433e-b808-e63e1cfd898d/d9b2935aebc7036e496511a85689b43b/v8.png)

## HyperFrames (finished)

| Field | Value |
| --- | --- |
| Session | https://reasonmachines.com/agents/19a2443a-391e-4e48-942f-bf54997676b2 |
| Draft PR | https://github.com/reason-machines/content-factory/pull/7 (not merged) |
| Engine | hyperframes CLI 0.8.169, GSAP 3.x timeline, system Chromium (screenshot capture, software GL) |
| Start | 17:52:38 |
| Engine ready (hello-world render) | 17:54:24 (+1m46s) |
| First full render done | 18:16:34 (+23m56s) |
| Final render done | 18:21:30 (+28m52s) |
| Final render wall time | 193.4 s (capture 185.5 s, ~19 fps) |
| Review passes | 2 of 2 (second pass found nothing, no re-render) |
| Output | 1920x1080, 60 fps, 3600 frames, H.264 High yuv420p CRF 16, AAC 48 kHz; soundtrack hash verified |

**Deviations:** small and similar in kind to Remotion's: added Slack chrome, a tax row so
totals add up, invented sub-agent log lines, median times drawn as bars, an Open→Merged pill
in the PR header, a lighter @Reason highlight so it reads on the dark window. Check ticks
follow the scripted 41.0–42.5 s window rather than "one per half-beat".

**Engine friction:** the fast BeginFrame capture was unavailable because the
chrome-headless-shell download was blocked by the sandbox proxy, so rendering fell back to
screenshot capture (still faster than Remotion here). Lint rejected tweening left/top
(fixed with clip-path) and could not see an external timeline script (inlined it). The
agent skill opens with an intent interview, skipped because the script is fixed.
`hyperframes snapshot --at` was a standout: 32 layout stills in 9 s.

**Video:** not published, same `media_publish_file` rejection of every video file. A 480p,
10 fps GIF (no audio) stands in, with the contact sheet:

![HyperFrames 480p 10 fps GIF preview, no audio](https://api.reasonmachines.com/media/pr-screenshots/19a2443a-391e-4e48-942f-bf54997676b2/482e7b8d9014b396f9801acc9ee99d50/preview.gif)

![HyperFrames contact sheet, 1 fps](https://api.reasonmachines.com/media/pr-screenshots/19a2443a-391e-4e48-942f-bf54997676b2/eaa8c534a223ea1f7a0c50a575fb6aa5/reason-demo-hyperframes-contact-sheet.jpg)

## FFrames 1.2

Running.
