"""
pipeline/word_align.py
──────────────────────
Dependency-free beat timing: estimates where each phrase of a voiceover starts
by weighting words by length/punctuation, then snapping phrase boundaries to
real pauses detected in the WAV with ffmpeg silencedetect.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Tuple

MIN_BEAT_SEC = 2.0


def detect_silences(wav_path: str | Path, noise_db: int = -35, min_dur: float = 0.12) -> List[Tuple[float, float]]:
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(wav_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    starts = [max(0.0, float(x)) for x in re.findall(r"silence_start: (-?[\d.]+)", res.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", res.stderr)]
    out: List[Tuple[float, float]] = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else s + min_dur
        out.append((s, e))
    return out


def _word_times(text: str, duration: float, silences: List[Tuple[float, float]]) -> List[float]:
    words = text.split()
    n = len(words)
    if n == 0:
        return [0.0]
    speech_start = silences[0][1] if silences and silences[0][0] <= 0.05 else 0.0
    speech_end = silences[-1][0] if silences and silences[-1][1] >= duration - 0.15 else duration
    if speech_end - speech_start < 0.5:
        speech_start, speech_end = 0.0, duration

    weights = []
    for w in words:
        core = re.sub(r"\W", "", w)
        wt = len(core) + 2.0
        if w.endswith((",", ";", ":")):
            wt += 3.0
        elif w.endswith((".", "?", "!")):
            wt += 6.0
        weights.append(wt)
    total = sum(weights)
    span = speech_end - speech_start
    times = [speech_start]
    acc = 0.0
    for wt in weights:
        acc += wt
        times.append(speech_start + span * acc / total)
    return times


def _snap(t: float, silences: List[Tuple[float, float]], window: float = 0.6) -> float:
    best, best_d = t, window
    for s, e in silences:
        mid = (s + e) / 2.0
        d = abs(mid - t)
        if d < best_d:
            best, best_d = mid, d
    return best


def phrase_durations(
    full_text: str,
    phrases: List[str],
    wav_path: str | Path,
    total_duration: float,
) -> List[float]:
    """Return one duration per phrase; they sum to total_duration."""
    n = len(phrases)
    if n <= 1:
        return [total_duration]

    silences = detect_silences(wav_path)
    times = _word_times(full_text, total_duration, silences)
    total_words = len(times) - 1

    counts = [max(1, len(p.split())) for p in phrases]
    scale = total_words / max(1, sum(counts))
    counts = [max(1, round(c * scale)) for c in counts]
    while sum(counts) > total_words and max(counts) > 1:
        counts[counts.index(max(counts))] -= 1
    while sum(counts) < total_words:
        counts[counts.index(min(counts))] += 1

    bounds = [0.0]
    idx = 0
    for c in counts[:-1]:
        idx += c
        bounds.append(_snap(times[min(idx, total_words)], silences))
    bounds.append(total_duration)

    for i in range(1, n):
        bounds[i] = max(bounds[i], bounds[i - 1] + MIN_BEAT_SEC)
    for i in range(n - 1, 0, -1):
        bounds[i] = min(bounds[i], bounds[i + 1] - MIN_BEAT_SEC)
    if any(bounds[i + 1] - bounds[i] < 1.0 for i in range(n)):
        step = total_duration / n
        bounds = [step * i for i in range(n)] + [total_duration]

    return [round(bounds[i + 1] - bounds[i], 3) for i in range(n)]
