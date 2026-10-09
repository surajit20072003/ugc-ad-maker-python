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
