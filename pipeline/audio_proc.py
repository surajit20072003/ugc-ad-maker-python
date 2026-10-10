"""
pipeline/audio_proc.py
───────────────────────
Helper for processing reference audio files for voice cloning.
"""
import os
import subprocess
from pathlib import Path

def process_reference_audio(input_path: Path, output_path: Path, max_duration: int = 15) -> None:
    """
    Convert the uploaded audio to a format VoxCPM optimally supports (16-bit WAV, 24kHz)
    and trim to a maximum duration (default 15 seconds) to prevent VRAM explosion.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-t", str(max_duration),     # Trim to max_duration seconds
        "-vn",                       # No video
        "-acodec", "pcm_s16le",      # 16-bit WAV
        "-ar", "24000",              # 24kHz sample rate (typical for TTS models)
        "-ac", "1",                  # Mono
        str(output_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to process reference audio:\n{result.stderr}")


def get_audio_duration_bytes(wav_bytes: bytes) -> float:
    """
    Measure exact audio duration in seconds from WAV bytes in memory.
    Uses Python's standard wave library, falling back to ffprobe if needed.
    """
    import io
    import wave

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0:
                return round(frames / float(rate), 3)
    except Exception:
        pass

    # Fallback via ffprobe through pipe
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            "-"
        ]
        res = subprocess.run(cmd, input=wav_bytes, capture_output=True, text=True, check=True)
        return round(float(res.stdout.strip()), 3)
    except Exception as e:
        # Default safety fallback estimation based on 16-bit 24kHz mono (48,000 bytes/sec)
        if len(wav_bytes) > 44:
            return round((len(wav_bytes) - 44) / 48000.0, 3)
        return 5.0


def get_audio_duration_file(file_path: Path | str) -> float:
    """Measure exact duration of an audio file in seconds."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        try:
            return round(float(res.stdout.strip()), 3)
        except ValueError:
            pass
    return 5.0

