#!/usr/bin/env python3
"""Shared soundtrack for the video-engine benchmark (stdlib only, deterministic).

Writes soundtrack.wav: 60.000 s, 48 kHz, 16-bit stereo, 120 BPM (one bar = 2 s).
Every engine uses this exact file so the comparison measures the engine, not the music.

Cue points (seconds) match SCRIPT.md scene boundaries:
  4.0 product   12.0 computer   22.0 parallel   30.0 survives
  38.0 proof    46.0 benchmark  54.0 ending     57.0 mark lands
"""
import math
import random
import struct
import sys
import wave

SR = 48000
DUR = 60.0
N = int(SR * DUR)
BEAT = 0.5
CUTS = [4.0, 12.0, 22.0, 30.0, 38.0, 46.0, 54.0]

random.seed(7)
L = [0.0] * N
R = [0.0] * N


def add(start, samples, pan=0.0, gain=1.0):
    """Mix a mono list into the stereo bus at time `start` (s); pan -1..1."""
    i0 = int(start * SR)
    gl = gain * math.cos((pan + 1) * math.pi / 4)
    gr = gain * math.sin((pan + 1) * math.pi / 4)
    for k, s in enumerate(samples):
        i = i0 + k
        if 0 <= i < N:
            L[i] += s * gl
            R[i] += s * gr


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def pad_note(freq, dur, attack=0.6, release=1.2, detune=0.004):
    n = int(dur * SR)
    out = [0.0] * n
    tw = 2 * math.pi / SR
    fs = (freq * (1 - detune), freq, freq * (1 + detune))
    for k in range(n):
        t = k / SR
        env = min(1.0, t / attack) * min(1.0, (dur - t) / release if dur - t < release else 1.0)
        v = 0.0
        for f in fs:
            p = tw * f * k
            v += math.sin(p) + 0.32 * math.sin(2 * p) + 0.12 * math.sin(3 * p)
        out[k] = v * env / 3
    return out


def kick(gain=1.0):
    n = int(0.42 * SR)
    out = [0.0] * n
    ph = 0.0
    for k in range(n):
        t = k / SR
        f = 48 + 110 * math.exp(-t * 28)
        ph += 2 * math.pi * f / SR
        out[k] = math.sin(ph) * math.exp(-t * 7.5) * gain
    return out


def hat(gain=1.0):
    n = int(0.06 * SR)
    prev = 0.0
    out = []
    for k in range(n):
        w = random.uniform(-1, 1)
        hp = w - prev  # crude high-pass
        prev = w
        out.append(hp * math.exp(-k / SR * 70) * gain)
    return out


def bass(freq, dur=0.22, gain=1.0):
    n = int(dur * SR)
    out = []
    for k in range(n):
        t = k / SR
        p = 2 * math.pi * freq * t
        v = math.sin(p) + 0.25 * math.sin(2 * p)
        out.append(v * min(1.0, t / 0.005) * math.exp(-t * 9) * gain)
    return out


def impact(gain=1.0):
    n = int(1.6 * SR)
    out = []
    lp = 0.0
    ph = 0.0
    for k in range(n):
        t = k / SR
        ph += 2 * math.pi * (38 + 50 * math.exp(-t * 10)) / SR
        lp += 0.08 * (random.uniform(-1, 1) - lp)
        out.append((0.9 * math.sin(ph) * math.exp(-t * 3.2) + 0.6 * lp * math.exp(-t * 5)) * gain)
    return out


def riser(dur=1.0, gain=1.0):
    n = int(dur * SR)
    out = []
    lp = 0.0
    for k in range(n):
        t = k / SR
        a = 0.01 + 0.25 * (t / dur) ** 2  # filter opens
        lp += a * (random.uniform(-1, 1) - lp)
        out.append(lp * (t / dur) ** 2 * gain)
    return out


def bell(freq, dur=3.0, gain=1.0):
    n = int(dur * SR)
    out = []
    for k in range(n):
        t = k / SR
        p = 2 * math.pi * freq * t
        v = math.sin(p) + 0.5 * math.sin(2.76 * p) * math.exp(-t * 3) + 0.25 * math.sin(5.4 * p) * math.exp(-t * 6)
        out.append(v * math.exp(-t * 1.6) * gain)
    return out


def shimmer(dur=4.0, gain=1.0):
    """Hook texture: a rising cluster of soft sine glints."""
    out = [0.0] * int(dur * SR)
    notes = [81, 84, 88, 91, 93, 96]
    for j in range(36):
        t0 = random.uniform(0, dur - 0.5)
        f = midi(random.choice(notes))
        g = 0.12 + 0.25 * (t0 / dur)
        i0 = int(t0 * SR)
        for k in range(int(0.5 * SR)):
            if i0 + k < len(out):
                t = k / SR
                out[i0 + k] += math.sin(2 * math.pi * f * t) * math.exp(-t * 8) * g
    return out


# --- arrangement -----------------------------------------------------------
# Progression, one chord per 4 s: F, C, Am, G (voiced around middle C).
CHORDS = [[53, 60, 65, 69], [48, 55, 64, 67], [45, 57, 60, 64], [43, 55, 59, 62]]
ROOTS = [41, 36, 45, 43]

# Pad: 0-58 s, quieter during the hook.
t = 0.0
ci = 0
while t < 54.0:
    for n in CHORDS[ci % 4]:
        add(t, pad_note(midi(n), 4.6), pan=random.uniform(-0.4, 0.4), gain=0.05 if t < 4 else 0.075)
    t += 4.0
    ci += 1
for n in [53, 60, 65, 69, 72]:  # final F chord rings out
    add(54.0, pad_note(midi(n), 6.0, attack=0.3, release=4.5), gain=0.085)

add(0.0, shimmer(4.0), gain=0.9)
add(3.0, riser(1.0), gain=0.5)

# Kick: half-time 4-12 s, every beat 12-45.5 and 47-54.
k = kick()
for i in range(int(4.0 / BEAT), int(54.0 / BEAT)):
    tb = i * BEAT
    if tb < 12.0 and i % 2:
        continue
    if 45.5 <= tb < 47.0:
        continue
    add(tb, k, gain=0.55)

# Hats on off-beats 12-54 s.
for i in range(int(12.0 / BEAT), int(54.0 / BEAT)):
    add(i * BEAT + BEAT / 2, hat(), pan=0.3, gain=0.16)

# Bass eighths 22-54 s on the chord root.
for i in range(int(22.0 / 0.25), int(54.0 / 0.25)):
    tb = i * 0.25
    if 45.5 <= tb < 47.0:
        continue
    add(tb, bass(midi(ROOTS[int(tb // 4) % 4])), gain=0.22)

for c in CUTS:
    add(c, impact(), gain=0.42 if c in (4.0, 46.0, 54.0) else 0.26)
for c in (21.0, 45.0, 53.0):
    add(c, riser(1.0), gain=0.35)
add(57.0, bell(midi(77)), pan=-0.1, gain=0.22)
add(57.0, bell(midi(84)), pan=0.1, gain=0.12)

# Master: fade the last 2 s, soft-clip, normalise to -1 dBFS.
for i in range(int(58.0 * SR), N):
    g = (N - i) / (2.0 * SR)
    L[i] *= g
    R[i] *= g
for buf in (L, R):
    for i in range(N):
        buf[i] = math.tanh(buf[i] * 1.2)
peak = max(max(abs(x) for x in L), max(abs(x) for x in R)) or 1.0
scale = 0.891 / peak

out = sys.argv[1] if len(sys.argv) > 1 else "soundtrack.wav"
with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    frames = bytearray()
    for i in range(N):
        frames += struct.pack("<hh", int(L[i] * scale * 32767), int(R[i] * scale * 32767))
    w.writeframes(bytes(frames))
print(f"wrote {out}: {DUR:.3f}s {SR} Hz stereo")
