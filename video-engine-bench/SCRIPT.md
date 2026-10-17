# "Its own computer": 60-second Reason demo

One script, implemented independently in three engines (Remotion, HyperFrames,
FFrames). Spec: 1920x1080, 60 fps, exactly 60.000 s (3600 frames), H.264 yuv420p +
AAC 48 kHz stereo, soundtrack from [`make_score.py`](make_score.py) (120 BPM, one bar
= 2 s; every scene boundary lands on a downbeat).

**Story.** A teammate asks for a fix in Slack, and Reason delivers it as a merged pull
request with proof. Along the way the viewer sees why it works: every Session has its
own computer, work runs in parallel, the agent outlives the machine, and the harness
beats Codex on the same model.

**Value props used** (content-writing-valueprops): #4 every session has its own
computer, #8 use it wherever you work (Slack), #12 parallel sessions (no count quoted),
#2 detached harness (moves between machines, survives a lost one, token never in the
sandbox), #5 end-to-end PR proof, #1 benchmarks (DeepSWE v1.1 73.0% vs Codex 70.8%,
13.8 vs 22.7 min median, $5.32 per attempt). Not claimed: #1 on DeepSWE, cheapest,
"hundreds" of sessions, SOC 2.

## House style (all scenes)

- Type: Helvetica Now Display **Regular only, never bold** (`public/fonts/HelveticaNowDisplay-Regular.woff2`);
  code and terminal in Geist Mono (`public/fonts/GeistMono-Regular.ttf`).
- Colours: paper `#f8f9f4`, ink `#14120b`, pale tint for word reveals `#d9d7d0`,
  muted `#85827b`, hairline `#e9e7e2`, terminal `#16120d` / text `#e9e6df` / muted `#8d887e`,
  dark app `#141414` / panel `#1c1c1c` / border `#2a2a2a` / text `#e4e4e4`,
  green `#1f9d55`, red `#e5484d`, link blue `#2f6fe4`, stage black `#000`.
  Mark palette: blue `#3e63dd`, green `#30a46c`, amber `#ffb224`, pink `#d6409f`,
  purple `#8e4ec6`, teal `#12a594`, orange `#f76b15`, red `#e5484d`.
- The Reason mark (the mascot): a flat-top rounded hexagon with two vertical "eye"
  strokes, `public/marks/reason-mark-*.svg` (viewBox 0 0 100 100). The rounded hex
  without eyes is the recurring tile shape.
- Textures: `public/marble/*.webp` fill the hex tiles of the opening and ending fields.
- Captions: centred, baseline about 150 px from the top, 60 px, letter-spacing
  -0.03em, each word revealing from the pale tint to ink over 14 frames with a 4-frame
  stagger. Optional sub-line 30 px muted, 16 frames after the caption. Product UI sits
  centred below the caption.
- Motion: ease-out cubic/expo or critically damped springs. No linear moves except
  counters and typing. No generic crossfades between scenes: push, scale or match-cut.
  Each scene's first action lands on its downbeat.
- Scenes 2-6 show a 22 px muted label bottom-left, 48 px from the edges: `Illustrative workflow`.
- Safe area: text stays inside 1760x980.

## Scenes

Times are global seconds (frame = s x 60).

### 1. Hook: 0.0-4.0 s (f0-239)

- f0: the frame is already full of rounded flat-top hex tiles (about 150 px wide, small
  gaps showing paper), each filled with a marble texture; about one tile in six holds a
  coloured Reason mark instead. Slow drift.
- 0.4-2.2 s: the tiles clear radially from the centre outward (scale down + fade,
  staggered by distance) onto paper. The centre tile survives and becomes the ink
  Reason mark, about 220 px.
- 1.8-3.0 s: the mark rises; "Reason" (120 px) resolves below it character by
  character from blur; then the line **"The coding agent with its own computer."**
  (52 px) reveals word by word.
- 3.5-4.0 s: the lockup lifts and shrinks away as the Slack window of scene 2 rises
  from below; the product is unobscured by f246. Impact on the 4.0 s downbeat.

### 2. The ask: 4.0-12.0 s

- Caption: **"Ask from wherever you work."**
- A dark Slack-style thread window (about 1280x620), channel `#checkout`.
- 4.3 s: Maya (`public/avatars/maya.jpg`) posts: "Checkout totals look wrong for
  customers in Japan. @Reason can you take a look?"
- 6.0 s: the `@Reason` mention lights up in link blue.
- 6.8 s: Reason replies (blue mark avatar): "On it. Started a Session in
  acme/storefront." with an inline session card: "Fix JPY totals in checkout ·
  Running" and a pulsing green dot.
- 10.0-12.0 s: push into the session card; it expands and match-cuts into the session
  window of scene 3.

### 3. Its own computer: 12.0-22.0 s

- Caption: **"Every Session gets its own computer."** Sub-line: "A full desktop,
  browser and terminal in the cloud. Not your laptop."
- The Reason app window (dark, about 1600x800): left column is the chat, right column
  the computer panel with tabs `Terminal` and `Browser`.
- Chat steps tick in as the work happens: "Cloning acme/storefront ✓",
  "Installing dependencies ✓", "Starting the dev server ✓", "Reproducing in the browser…".
- 12.8-16.5 s, Terminal tab, typed fast:
  `$ git clone acme/storefront` · `$ bun install` → `1,284 packages installed` ·
  `$ bun dev` → `ready on http://localhost:3000`.
- 16.5 s: the panel switches to Browser: a clean light checkout page, "Order summary",
  three line items, Subtotal **¥12,480.00**, Total **¥13,728.00**. A cursor moves to
  the total; a red ring draws around ".00" with the note "Yen has no minor unit".
- 19.5 s: chat: "Found it: formatPrice() always prints two decimals."
- 21.0-22.0 s: the window scales back and flies up into scene 4.

### 4. Parallel: 22.0-30.0 s

- Caption: **"Big tasks split up and run in parallel."**
- The session card sits top centre. 22.6 s: three lines branch from it (a dot travels
  each) to three sub-agent cards, each with its own coloured mark (blue, green, amber):
  1. "Fix formatPrice for zero-decimal currencies"
  2. "Add regression tests for JPY, KRW and VND"
  3. "Check every page that shows a price"
- Each card shows live activity (a few mono lines ticking, a thin progress bar).
  They finish on beats: 26.0, 27.0, 28.0 s, each flipping to a green "✓ Done".
- 28.5-30.0 s: the three fold back into the main card: "3 of 3 finished · one branch".

### 5. The agent outlives the machine: 30.0-38.0 s

- Caption: **"The agent runs outside the machine."** Sub-line: "Sessions move between
  computers and survive losing one."
- Left: a large Reason mark labelled "Reason harness". Right: three machine tiles in a
  column: "Cloud Linux", "Cloud Mac", "Your Mac". A tether runs from the mark to Cloud
  Linux, with the session progress bar on it at 62%.
- 31.5 s: Cloud Linux flickers red, greys out: "Machine lost".
- 32.3 s: the tether swings to Cloud Mac (a dot travels it): "Reconnected · state
  restored". The progress bar continues from 62%, not from zero.
- 34.0 s: inside the Cloud Mac tile, a small browser shows the checkout total now
  reading ¥13,728: "Verified on a cloud Mac".
- 36.0 s: footnote line, 28 px muted: "Your GitHub token never enters the sandbox."

### 6. Proof: 38.0-46.0 s

- Caption: **"Pull requests arrive with proof."**
- A light PR panel (white card on paper): "Fix JPY totals in checkout #482", branch
  chip, "Reason opened this pull request".
- 39.0 s: before/after screenshots slide in side by side: Before "¥13,728.00" (red
  tint), After "¥13,728" (green tint); next to them a walkthrough video thumbnail with
  a play glyph: "walkthrough.mp4 · 0:24".
- 41.0-42.5 s, one per half-beat, checks tick green: "Unit tests · 214 passed",
  "Regression: JPY, KRW, VND · 9 passed", "Typecheck", "Lint".
- 43.5 s: the Merge button presses; a purple "Merged" pill replaces it. 44.2 s: a small
  Slack toast slides in bottom right: "Reason: Fixed and merged. Totals now show ¥13,728."

### 7. Same model, better harness: 46.0-54.0 s

- Black stage, white type. Caption: **"Same model. Better harness."**
- 46.6-48.6 s: two horizontal bars on an honest 0-100% axis count up together:
  "Reason 73.0%" (white) and "Codex 70.8%" (grey `#5a5a5a`). Label above: "DeepSWE v1.1 · pass@1".
- 49.5 s: second row: median solve time "13.8 min" vs "22.7 min", with a small pill
  "39% faster".
- 51.0 s: "$5.32 per attempt" (36 px).
- Footnote, 24 px `#8a8a8a`, visible 47.0-54.0 s: "DeepSWE v1.1, 113 tasks. Both on
  GPT-6 Astra at xhigh effort. Reason harness vs Codex."

### 8. Ending: 54.0-60.0 s

- 54.0 s: a dense hex field (marble tiles plus coloured marks, as in the hook) rushes
  in from the edges and covers the frame by 55.2 s.
- 55.5-56.8 s: the tiles scatter outward, leaving paper and one surviving ink Reason
  mark at centre (about 240 px).
- 57.0 s, on the bell: the mark blinks once (eye strokes squash to dots and back over
  10 frames).
- 57.2 s: "reasonmachines.com" (56 px) resolves character by character from blur below
  the mark.
- 58.0-60.0 s: hold (the audio fades out); the last frame is the clean lockup.
