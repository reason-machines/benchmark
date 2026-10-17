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

## FFrames 1.2 (finished)

| Field | Value |
| --- | --- |
| Session | https://reasonmachines.com/agents/33f56bfb-4b3b-4e79-9a03-44057a8edbcb |
| Draft PR | https://github.com/reason-machines/content-factory/pull/8 (not merged) |
| Engine | FFrames 1.2.0 (cargo-fframes 1.2.0), CPU tiny-skia backend |
| Start | 17:52:44 |
| Engine ready | 17:59:21 (+6m37s) |
| First full render done | 18:16:23 (+23m39s) |
| Final render done | 18:26:47 (+34m03s) |
| Final render wall time | 67.5 s real (user 257.9 s, ~53 fps) |
| Review passes | 2 of 2, plus one audio-only re-render (AAC defaulted to 44.1 kHz, set to 48 kHz) |
| Output | 1920x1080, 60 fps, 3600 frames, H.264 High yuv420p CRF 18, AAC LC 48 kHz stereo, 16.1 MB |

**Deviations:** same kind as the others: added Slack chrome, a tax row, invented sub-agent
log lines, an Open→Merged pill, axis tick labels and a minutes count-up. The fonts have no ✓
glyph, so every check is a drawn vector placed left of its text. The scene 3 window is
1560x740 to fit the safe area. Easing is hand-written on global time rather than the
`timeline!` macro.

**Engine friction:** the most setup work of the three. No root or apt, so libclang came
from a PyPI wheel; the prebuilt FFmpeg links x264 ABI 163 while Debian 12 ships 164 (fixed
by extracting libx264-163 from the Ubuntu archive and linking with an rpath); fframes.studio
is blocked by the network allowlist (used the skill from GitHub raw). `Overlap::Next` starts
the next scene earlier instead of extending the current one, so the ending redraws scene 7
by hand. Embedded audio is mono, so the soundtrack loads at run time. Rendering itself was
by far the fastest.

**Video:** not published, same `media_publish_file` rejection. Contact sheet and stills:

![FFrames contact sheet, 1 fps](https://api.reasonmachines.com/media/pr-screenshots/33f56bfb-4b3b-4e79-9a03-44057a8edbcb/2a2c27b64efdadf99872ebcc2afa5227/contact-sheet.png)

![FFrames protocol stills at 2, 8, 17, 26, 34, 42, 50, 57.5 s](https://api.reasonmachines.com/media/pr-screenshots/33f56bfb-4b3b-4e79-9a03-44057a8edbcb/0d020872ed2605499014d58be95c9a78/stills.png)

## Head-to-head

| | Remotion 4 | HyperFrames | FFrames 1.2 |
| --- | --- | --- | --- |
| Engine ready | +1m46s | +1m46s | +6m37s |
| First full render | +20m24s | +23m56s | +23m39s |
| Done | **+26m40s** | +28m52s | +34m03s |
| Final render, 60 s at 60 fps | 323.9 s (~11 fps) | 193.4 s (~19 fps) | **67.5 s (~53 fps)** |
| Review passes | 2 | 2 (second clean) | 2 + audio-only re-render |
| Spec (1080p60, 3600 frames, 48 kHz, soundtrack) | pass | pass | pass |
| Scripted copy and benchmark figures | exact | exact | exact |

All three ran on identical 4-vCPU cloud machines with the same model and limits. Every run
finished well inside the 60-minute soft limit.

**Quality, judged from stills only.** I compared the eight protocol stills and the 1 fps
contact sheets side by side. Motion, easing, beat sync and audio were not judged, because no
MP4 could be published and they could not be watched.

- **Remotion: best of the three by a small margin.** The UI cards are the largest and most
  legible at 1080p, the layouts fill the frame, and the PR, failover and benchmark scenes read
  cleanly. Nothing looked broken.
- **FFrames: close second.** The layouts and typography are about as polished as Remotion's,
  and the drawn vector checks look native. The before/after shots in scene 6 use grey
  placeholder bars, which look a little more generic.
- **HyperFrames: competent but the least legible.** The windows and cards are visibly smaller
  with more empty space, so the sub-agent cards and the Slack text are small at 1080p. This
  is judged from a 480p GIF and a JPEG contact sheet, so fine detail is less certain than for
  the other two.

All three share the same house style because they built the same script, so the quality
spread is narrow. None has a visible defect in the sampled frames.

**Takeaways**

1. **Fastest from script to finished cut: Remotion.** It needed no toolchain work, and its
   React mental model kept the agent's two passes short.
2. **Fastest renderer: FFrames, by 2.9x over HyperFrames and 4.8x over Remotion.** Its 6m37s
   setup was toolchain repair specific to this sandbox (libclang, x264 ABI). A prebuilt image
   would remove most of it, and then its render speed matters most for many variants or long
   videos.
3. **HyperFrames had the best review loop.** `snapshot --at` rendered 32 stills in 9 s.
   Rendering was handicapped here: without the blocked headless-shell download it had to
   fall back to screenshot capture, so 193 s is a floor case.
4. **One sandbox issue hit two engines.** Remotion and HyperFrames both lost their
   headless-shell download to the proxy. Allow-listing it, or caching it in the machine
   image, would make both faster to start and HyperFrames faster to render.

**Gap shared by every run:** `media_publish_file` rejected every video file, including a
2 s synthetic test clip, on all three machines. That is a tool-side issue unrelated to the
engines, and it is why no MP4 is linked here.
