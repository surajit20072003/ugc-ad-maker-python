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
            sampwidth = wf.getsampwidth()
            nchannels = wf.getnchannels()
            bytes_per_frame = sampwidth * nchannels
            if bytes_per_frame > 0:
                actual_max_frames = (len(wav_bytes) - 44) // bytes_per_frame
                if frames > actual_max_frames or frames <= 0:
                    frames = actual_max_frames
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


def normalize_wav_loudness(wav_bytes: bytes, target_lufs: float = -16.0) -> bytes:
    """
    Normalize WAV bytes to EBU R128 loudness standard (-16 LUFS by default).

    Ensures all TTS segment WAVs enter WaveSpeed lip-sync and ffmpeg b-roll mux
    at identical loudness — prevents the 'different voice' effect caused by
    WaveSpeed's internal AGC re-encoding vs raw ffmpeg amerge mux.

    Args:
        wav_bytes: Raw WAV audio bytes from TTS engine
        target_lufs: Target integrated loudness in LUFS (default -16 for broadcast)

    Returns:
        Loudness-normalized WAV bytes at 24kHz 16-bit mono, or original on failure.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as in_f:
        in_f.write(wav_bytes)
        in_path = in_f.name

    out_path = in_path.replace(".wav", "_norm.wav")

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", in_path,
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=none",
            "-ar", "24000",
            "-ac", "1",
            "-acodec", "pcm_s16le",
            out_path
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return wav_bytes   # Non-fatal: original audio beats silence
        return Path(out_path).read_bytes()
    except Exception:
        return wav_bytes       # Non-fatal fallback
    finally:
        Path(in_path).unlink(missing_ok=True)
        try:
            Path(out_path).unlink(missing_ok=True)
        except Exception:
            pass
