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

## HyperFrames

Running.

## FFrames 1.2

Running.
