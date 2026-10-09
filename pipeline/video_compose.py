"""
pipeline/video_compose.py
──────────────────────────
Download video clips from local or remote URLs, normalize them,
mux audio if needed, stitch clips into a single final UGC video with ffmpeg,
and optionally burn animated captions.

COMPOSITION FLOW:
  1. Download each clip (hook.mp4, body.mp4, cta.mp4)
  2. If clip has no audio, mux corresponding segment voiceover or silent audio
  3. Re-encode each to common spec (720p 9:16, 30fps, H264, AAC)
  4. Concat all clips in order: hook → body → cta
  5. Optionally burn in bold UGC-style subtitles
  6. Save final_{job_id}.mp4 to ./uploads/ and return server URL
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import httpx

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")


async def _download_video(url: str, dest: Path) -> None:
    """Download a video from URL to local destination."""
    # Check if already local
    if url.startswith(SERVER_URL):
        rel = url.replace(SERVER_URL, "").lstrip("/")
        local_src = Path(__file__).parent.parent / rel
        if local_src.exists():
            dest.write_bytes(local_src.read_bytes())
            return

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)


def _has_audio(path: Path) -> bool:
    """Check if video file contains an audio stream."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return bool(r.stdout.strip())


def _reencode_clip(
    src: Path,
    dst: Path,
    audio_src: Optional[Path] = None,
    width: int = 720,
    height: int = 1280,
    prefer_native_audio: bool = True,
) -> None:
    """
    Re-encode a video clip to 720x1280 (9:16), 30fps, H.264 CRF 19, AAC stereo 48kHz.
    Preserves native audio when present (vital for HeyGen lip-sync realism).
    Applies audio loudness normalization (-16 LUFS) and subtle cut-point anti-pop fades.
    """
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,fps=30"
    )

    has_audio = _has_audio(src)
    v_dur = _get_duration(src)
    fade_out_start = max(0.0, v_dur - 0.04)

    # Audio normalization filter: -16 LUFS (standard social media loudness)
    # plus subtle 30ms edge fades to prevent digital popping at cut boundaries
    af_native = (
        f"loudnorm=I=-16:TP=-1.5:LRA=11,"
        f"afade=t=in:ss=0:d=0.03,"
        f"afade=t=out:st={fade_out_start:.3f}:d=0.03"
    )

    if has_audio and prefer_native_audio:
        # Clip already contains its own synchronized speech (HeyGen avatar).
        # We PRESERVE the native speech to maintain 100% exact lip-sync!
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src),
            "-vf", vf,
            "-af", af_native,
            "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
            "-movflags", "+faststart",
            str(dst),
        ]
    elif audio_src and audio_src.exists():
        # Video is silent; mux the external voiceover audio
        a_dur = _get_duration(audio_src)
        a_fade_out = max(0.0, a_dur - 0.04)
        af_ext = (
            f"loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"afade=t=in:ss=0:d=0.03,"
            f"afade=t=out:st={a_fade_out:.3f}:d=0.03"
        )
        if v_dur < a_dur:
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", str(src),
                "-i", str(audio_src),
                "-vf", vf,
                "-af", af_ext,
                "-map", "0:v:0", "-map", "1:a:0",
                "-t", f"{a_dur:.3f}",
                "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
                "-movflags", "+faststart",
                str(dst),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(src),
                "-i", str(audio_src),
                "-vf", vf,
                "-af", af_ext,
                "-map", "0:v:0", "-map", "1:a:0",
                "-t", f"{a_dur:.3f}",
                "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
                "-movflags", "+faststart",
                str(dst),
            ]
    else:
        # Fallback silent audio stream to ensure stable concatenation
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf", vf,
            "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(dst),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg re-encode failed:\n{result.stderr[-800:]}")


def _concat_clips(clip_paths: list[Path], output: Path) -> None:
    """Concatenate multiple re-encoded clips using ffmpeg concat filter with studio quality."""
    if len(clip_paths) == 1:
        cmd = ["ffmpeg", "-y", "-i", str(clip_paths[0]), "-c", "copy", str(output)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg copy failed:\n{result.stderr[-800:]}")
        return

    inputs = []
    for p in clip_paths:
        inputs += ["-i", str(p)]

    n = len(clip_paths)
    filter_parts = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    filter_complex = f"{filter_parts}concat=n={n}:v=1:a=1[outv][outa]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed:\n{result.stderr[-800:]}")


def _get_duration(path: Path) -> float:
    """Return video duration in seconds."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _build_srt(segments: list[dict], clip_durations: list[float]) -> str:
    """Build an SRT subtitle file from script segments and clip durations."""
    def srt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    srt_lines = []
    idx = 1
    cursor = 0.0
    words_per_line = 4

    for seg, dur in zip(segments, clip_durations):
        words = seg.get("text", "").split()
        if not words or dur <= 0:
            cursor += dur
            continue

        secs_per_word = dur / len(words)
        pos = 0

        while pos < len(words):
            chunk = words[pos: pos + words_per_line]
            start = cursor + pos * secs_per_word
            end   = cursor + (pos + len(chunk)) * secs_per_word
            end   = min(end, cursor + dur - 0.05)
            text  = " ".join(chunk).upper()

            srt_lines.append(f"{idx}")
            srt_lines.append(f"{srt_time(start)} --> {srt_time(end)}")
            srt_lines.append(text)
            srt_lines.append("")

            idx += 1
            pos += words_per_line

        cursor += dur

    return "\n".join(srt_lines)


def _burn_captions(video_in: Path, srt_path: Path, video_out: Path) -> None:
    """Burn UGC-style bold captions into the video with clean high-contrast styling."""
    subs_filter = (
        f"subtitles='{srt_path}':"
        "force_style='FontName=DejaVu Sans,"
        "FontSize=22,"
        "Bold=1,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "Outline=2.6,"
        "Shadow=1.2,"
        "Alignment=2,"
        "MarginV=55'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-vf", subs_filter,
        "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(video_out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg caption burn failed:\n{result.stderr[-800:]}")


async def compose_final_video(
    clip_urls: list[str],
    segments: list[dict],
    job_id: str,
    burn_captions: bool = True,
    audio_urls: Optional[list[str]] = None,
) -> str:
    """
    Download clips, stitch them together, optionally burn captions.
    """
    UPLOAD_DIR.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # 1. Download video clips
        raw_paths: list[Path] = []
        dl_tasks = []
        for i, url in enumerate(clip_urls):
            dest = tmp_path / f"raw_{i}.mp4"
            raw_paths.append(dest)
            dl_tasks.append(_download_video(url, dest))

        # Download audio files if provided
        audio_paths: list[Optional[Path]] = [None] * len(clip_urls)
        if audio_urls:
            for i, aurl in enumerate(audio_urls):
                if aurl and i < len(clip_urls):
                    adest = tmp_path / f"audio_{i}.wav"
                    audio_paths[i] = adest
                    dl_tasks.append(_download_video(aurl, adest))

        await asyncio.gather(*dl_tasks)

        # 2. Re-encode clips to unified spec
        encoded_paths: list[Path] = []
        for i, raw in enumerate(raw_paths):
            enc = tmp_path / f"enc_{i}.mp4"
            asrc = audio_paths[i] if i < len(audio_paths) else None
            await asyncio.get_event_loop().run_in_executor(
                None, _reencode_clip, raw, enc, asrc
            )
            encoded_paths.append(enc)

        # 3. Concatenate
        concat_out = tmp_path / "concat.mp4"
        await asyncio.get_event_loop().run_in_executor(
            None, _concat_clips, encoded_paths, concat_out
        )

        # 4. Burn subtitles if requested
        if burn_captions and segments:
            durations = [_get_duration(p) for p in encoded_paths]
            srt_content = _build_srt(segments, durations)
            srt_path = tmp_path / "captions.srt"
            srt_path.write_text(srt_content, encoding="utf-8")

            captioned_out = tmp_path / "captioned.mp4"
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, _burn_captions, concat_out, srt_path, captioned_out
                )
                final_tmp = captioned_out
            except RuntimeError:
                final_tmp = concat_out
        else:
            final_tmp = concat_out

        # 5. Save to uploads/
        final_name = f"final_{job_id}.mp4"
        final_path = UPLOAD_DIR / final_name
        final_path.write_bytes(final_tmp.read_bytes())

    return f"{SERVER_URL}/uploads/{final_name}"


async def save_single_clip(
    clip_url: str,
    segments: list[dict],
    job_id: str,
    burn_captions: bool = True,
    audio_urls: Optional[list[str]] = None,
) -> str:
    return await compose_final_video(
        clip_urls=[clip_url],
        segments=segments,
        job_id=job_id,
        burn_captions=burn_captions,
        audio_urls=audio_urls,
    )
