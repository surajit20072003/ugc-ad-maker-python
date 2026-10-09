"""
main.py
────────
FastAPI UGC Ad Maker — Python backend

PIPELINE (3-segment UGC video generation):
  1. ANALYZE     → Claude Vision forensic analysis (colors, text, packaging, locked creator profile)
  2. SCRIPT      → Claude writes 3-segment UGC script + Director Scene Plan [HOOK] [BODY] [CTA]
  3. IMAGE GEN   → Generate 3 avatar images with consistent character identity & segment-specific poses
  4. TTS         → VoxCPM generates emotional voiceover per segment (or voice-cloned reference)
  5. UPLOAD      → Save audio/image files, make server-accessible
  6. VIDEO GEN   → Multi-Engine:
                   - WaveSpeed InfiniteTalk (Talking Avatar & Hand Gestures)
                   - OpenRouter AI Video (Veo 3.1, Seedance, Kling, Wan, HeyGen)
  7. COMPOSE     → ffmpeg: stitch clips + optional bold UGC caption burn → final.mp4

Routes:
  GET  /                  → UI
  POST /generate          → start pipeline, return job_id
  GET  /status/{job_id}   → SSE progress stream
  GET  /result/{job_id}   → full result JSON
  POST /upload/avatar     → upload avatar image → server URL
  GET  /health/voxcpm     → VoxCPM health check
  GET  /emotions          → TTS emotion list
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

import aiofiles  # noqa: F401
from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from pipeline.analyze import analyze_physical_product, analyze_software_product
from pipeline.audio_proc import process_reference_audio
from pipeline.image_gen import generate_ugc_prompt, generate_ugc_image
from pipeline.script_gen import generate_script
from pipeline.script_split import parse_segments, segments_to_full_script, format_script_for_display
from pipeline.tts import generate_voiceover, list_emotions, check_health
from pipeline.upload import upload_audio_wav, upload_image_bytes
from pipeline.video_gen import generate_video
from pipeline.video_compose import compose_final_video, save_single_clip

load_dotenv()

# ─── App setup ───────────────────────────────────────────────────────────────

app = FastAPI(title="UGC Ad Maker", version="3.1.0")

BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app.mount("/static",  StaticFiles(directory=BASE_DIR / "static"),  name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR),           name="uploads")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# In-memory job store
JOBS: Dict[str, dict] = {}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _job(job_id: str) -> dict:
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return JOBS[job_id]


def _emit(job_id: str, step: str, message: str, progress: int, **extra) -> None:
    if job_id in JOBS:
        timestamp = time.strftime("%H:%M:%S")
        entry = {"step": step, "message": message, "progress": progress, "time": timestamp, **extra}
        JOBS[job_id]["steps"].append(entry)
        JOBS[job_id]["current_step"] = step
        JOBS[job_id]["progress"]     = progress
        print(f"[{timestamp}] [{job_id[:8]}] [{step.upper()}] ({progress}%): {message}", flush=True)


# ─── Pipeline ────────────────────────────────────────────────────────────────

async def run_pipeline(
    job_id: str,
    product_name: str,
    product_benefit: str,
    product_mode: str,
    product_image_url: str,
    product_image_bytes: bytes,
    product_image_mime: str,
    avatar_url: str,
    voice_emotion: str,
    ugc_image_model: str,
    burn_captions: bool,
    video_backend: str = "openrouter",
    openrouter_video_model: str = "heygen/heygen-video-1",
    custom_script: str = "",
    reference_audio_path: str = "",
) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    job["video_backend"] = video_backend
    job["openrouter_video_model"] = openrouter_video_model

    try:
        # ────────────────────────────────────────────────────────────────────
        # Step 1: Deep Forensic Product Analysis & Character Profile
        # ────────────────────────────────────────────────────────────────────
        _emit(job_id, "analyze", "Analyzing product, branding & colors (Claude Vision)...", 5)

        if product_mode == "software":
            analysis = await analyze_software_product(product_name, product_benefit or "Software Product")
        else:
            analysis = await analyze_physical_product(
                image_url=product_image_url or None,
                image_bytes=product_image_bytes or None,
                image_mime=product_image_mime,
            )
        job["analysis"] = analysis

        # ────────────────────────────────────────────────────────────────────
        # Step 2: Generate or Parse Screenplay + Director Scene Plan
        # ────────────────────────────────────────────────────────────────────
        if custom_script and custom_script.strip():
            _emit(job_id, "script", "Parsing your custom screenplay & scenes...", 12)
            raw_script = custom_script.strip()
            segments = parse_segments(raw_script)
            full_script = segments_to_full_script(segments)
            display_script = format_script_for_display(raw_script)
        else:
            _emit(job_id, "script", "Writing Director's 3-segment UGC screenplay...", 12)
            raw_script = await generate_script(
                product_name, product_benefit,
                mode=product_mode, analysis=analysis,
            )
            segments = parse_segments(raw_script)
            full_script = segments_to_full_script(segments)
            display_script = format_script_for_display(raw_script)

        _emit(job_id, "script", f"Screenplay locked: {len(segments)} scenes ready ({', '.join(s['label'] for s in segments)})", 16)

        job["script"]         = full_script
        job["raw_script"]     = raw_script
        job["display_script"] = display_script
        job["segments"]       = segments

        # ────────────────────────────────────────────────────────────────────
        # Step 3: Generate Consistent Avatar Images (One Per Segment)
        # ────────────────────────────────────────────────────────────────────
        segment_image_urls: list[str] = []

        if avatar_url:
            _emit(job_id, "image_gen", f"Using custom creator avatar for all {len(segments)} scenes...", 20)
            segment_image_urls = [avatar_url] * len(segments)
        else:
            _emit(job_id, "image_gen",
                  f"Generating {len(segments)} consistent creator scenes (waist-up + gestures)...", 18)

            ref_image_url = product_image_url
            if not ref_image_url and product_image_bytes:
                _emit(job_id, "upload_product", "Uploading product reference...", 20)
                ref_image_url = await upload_image_bytes(product_image_bytes, job_id)

            # Generate prompts using consistent character anchor + director scene cues
            prompt_tasks = [
                generate_ugc_prompt(
                    product_name, analysis,
                    mode=product_mode,
                    segment=seg["label"],
                    scene_direction=seg.get("scene_direction"),
                )
                for seg in segments
            ]
            ugc_prompts = await asyncio.gather(*prompt_tasks)

            # Generate images in parallel
            _emit(job_id, "image_gen", "Rendering photorealistic creator poses...", 25)
            image_tasks = [
                generate_ugc_image(
                    prompt,
                    ref_image_url,
                    model=ugc_image_model,
                    job_id=f"{job_id}_{i}",
                )
                for i, prompt in enumerate(ugc_prompts)
            ]
            segment_image_urls = list(await asyncio.gather(*image_tasks))

        job["ugc_image_url"] = segment_image_urls[0] if segment_image_urls else ""
        job["segment_image_urls"] = segment_image_urls

        # ────────────────────────────────────────────────────────────────────
        # Step 4: Generate Voiceover per Segment (VoxCPM)
        # ────────────────────────────────────────────────────────────────────
        _emit(job_id, "tts", f"Generating voiceovers for {len(segments)} scenes (VoxCPM emotional speech)...", 30)

        async def _gen_single_tts(idx: int, seg: dict):
            label = seg.get("label", f"scene_{idx+1}")
            emotion = seg.get("emotion", "encourage")
            _emit(job_id, "tts", f"🎙️ [Scene {idx+1}/{len(segments)}] VoxCPM generating voiceover (emotion: {emotion})...", 30 + int((idx / len(segments)) * 18))
            wav = await generate_voiceover(seg["text"], emotion=emotion, reference_audio=reference_audio_path)
            _emit(job_id, "tts", f"✅ [Scene {idx+1}/{len(segments)}] Audio ready ({len(wav) // 1024} KB)", 30 + int(((idx + 1) / len(segments)) * 18))
            return wav

        tts_tasks = [_gen_single_tts(i, seg) for i, seg in enumerate(segments)]
        wav_bytes_list: list[bytes] = list(await asyncio.gather(*tts_tasks))

        # ────────────────────────────────────────────────────────────────────
        # Step 5: Upload Audio Files
        # ────────────────────────────────────────────────────────────────────
        _emit(job_id, "upload_audio", f"Saving {len(wav_bytes_list)} audio WAV files for video muxing...", 50)

        audio_upload_tasks = [
            upload_audio_wav(wav, f"{job_id}_{i}")
            for i, wav in enumerate(wav_bytes_list)
        ]
        audio_urls: list[str] = list(await asyncio.gather(*audio_upload_tasks))
        job["audio_url"]  = audio_urls[0] if audio_urls else ""
        job["audio_urls"] = audio_urls

        # ────────────────────────────────────────────────────────────────────
        # Step 6: Generate Video Clips (WaveSpeed or OpenRouter)
        # ────────────────────────────────────────────────────────────────────
        engine_label = f"OpenRouter ({openrouter_video_model})" if video_backend == "openrouter" else "WaveSpeed InfiniteTalk"
        _emit(job_id, "video", f"Generating {len(segments)} video clips ({engine_label})...", 55)

        async def _gen_single_video(idx: int, seg: dict):
            label = seg.get("label", f"scene_{idx+1}")
            pct_base = 55 + int((idx / len(segments)) * 32)
            _emit(job_id, "video", f"🎬 Dispatching Scene {idx+1}/{len(segments)} ({label}) to {engine_label}...", pct_base)

            def _log_cb(msg: str):
                _emit(job_id, "video", f"[Scene {idx+1}/{len(segments)}] {msg}", pct_base)

            clip = await generate_video(
                image_url=segment_image_urls[idx],
                audio_url=audio_urls[idx] if idx < len(audio_urls) else "",
                script=seg["text"],
                segment=seg["label"],
                resolution="720p",
                backend=video_backend,
                openrouter_model=openrouter_video_model,
                scene_prompt=seg.get("scene_prompt", ""),
                on_log=_log_cb,
            )
            _emit(job_id, "video", f"✅ [Scene {idx+1}/{len(segments)}] Video clip successfully generated!", pct_base + int(32 / len(segments)))
            return clip

        video_tasks = [_gen_single_video(i, seg) for i, seg in enumerate(segments)]
        clip_urls: list[str] = list(await asyncio.gather(*video_tasks))
        job["clip_urls"] = clip_urls

        # ────────────────────────────────────────────────────────────────────
        # Step 7: Compose Final Video (Concatenation + Subtitles)
        # ────────────────────────────────────────────────────────────────────
        _emit(job_id, "compose",
              f"Stitching {len(clip_urls)} clips + burning dynamic UGC captions (ffmpeg)...", 90)

        if len(clip_urls) == 1:
            video_url = await save_single_clip(
                clip_url=clip_urls[0],
                segments=segments,
                job_id=job_id,
                burn_captions=burn_captions,
                audio_urls=audio_urls,
            )
        else:
            video_url = await compose_final_video(
                clip_urls=clip_urls,
                segments=segments,
                job_id=job_id,
                burn_captions=burn_captions,
                audio_urls=audio_urls,
            )

        job["video_url"] = video_url

        # ────────────────────────────────────────────────────────────────────
        # Done
        # ────────────────────────────────────────────────────────────────────
        _emit(
            job_id, "done", "Your UGC ad is ready!", 100,
            job_id=job_id,
            video_url=video_url,
            script=job.get("script", ""),
            raw_script=job.get("raw_script", ""),
            display_script=job.get("display_script", ""),
            audio_url=job.get("audio_url", ""),
            ugc_image_url=job.get("ugc_image_url", ""),
            segments=job.get("segments", []),
            clip_urls=job.get("clip_urls", []),
            analysis=job.get("analysis", {}),
        )
        job["status"] = "completed"

    except Exception as exc:
        _emit(job_id, "error", f"Error: {exc}", job.get("progress", 0))
        job["status"] = "failed"
        job["error"]  = str(exc)


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload/avatar")
async def upload_avatar(file: UploadFile = File(...)):
    """Upload avatar photo → returns server CDN URL."""
    image_bytes = await file.read()
    mime = file.content_type or "image/jpeg"
    if not mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    job_id  = str(uuid.uuid4())[:8]
    cdn_url = await upload_image_bytes(image_bytes, job_id)
    return {"url": cdn_url}


@app.post("/generate")
async def generate(
    product_name:           str            = Form(...),
    product_benefit:        str            = Form(""),
    product_mode:           str            = Form("physical"),
    product_image_url:      str            = Form(""),
    voice_emotion:          str            = Form("excited"),
    ugc_image_model:        str            = Form("google/gemini-2.5-flash-image"),
    avatar_url:             str            = Form(""),
    burn_captions:          str            = Form("true"),
    video_backend:          str            = Form("wavespeed"),
    openrouter_video_model: str            = Form("google/veo-3.1-fast"),
    custom_script:          str            = Form(""),
    product_image_file:     Optional[UploadFile] = File(None),
    reference_audio_file:   Optional[UploadFile] = File(None),
):
    """Kick off the UGC pipeline with selectable video backend."""
    job_id = str(uuid.uuid4())

    product_image_bytes = b""
    product_image_mime  = "image/jpeg"
    if product_image_file and product_image_file.filename:
        product_image_bytes = await product_image_file.read()
        product_image_mime  = product_image_file.content_type or "image/jpeg"

    if (
        product_mode == "physical"
        and not avatar_url
        and not product_image_url
        and not product_image_bytes
    ):
        raise HTTPException(
            status_code=400,
            detail="Physical product mode requires a product image (URL or file upload).",
        )

    do_captions = burn_captions.lower() not in ("false", "0", "no")

    # Process reference audio if uploaded
    ref_audio_path_str = ""
    if reference_audio_file and reference_audio_file.filename:
        raw_audio_path = UPLOAD_DIR / f"raw_audio_{job_id}.tmp"
        with open(raw_audio_path, "wb") as buffer:
            buffer.write(await reference_audio_file.read())

        processed_audio_path = UPLOAD_DIR / f"ref_audio_{job_id}.wav"
        try:
            process_reference_audio(raw_audio_path, processed_audio_path, max_duration=15)
            ref_audio_path_str = str(processed_audio_path.resolve())
        except Exception as e:
            print(f"Failed to process reference audio for job {job_id}: {e}")
        finally:
            if raw_audio_path.exists():
                raw_audio_path.unlink()

    JOBS[job_id] = {
        "job_id":                 job_id,
        "status":                 "queued",
        "product_name":           product_name,
        "product_mode":           product_mode,
        "video_backend":          video_backend,
        "openrouter_video_model": openrouter_video_model,
        "progress":               0,
        "current_step":           "queued",
        "steps":                  [],
        "created_at":             time.time(),
    }

    asyncio.create_task(run_pipeline(
        job_id=job_id,
        product_name=product_name,
        product_benefit=product_benefit,
        product_mode=product_mode,
        product_image_url=product_image_url,
        product_image_bytes=product_image_bytes,
        product_image_mime=product_image_mime,
        avatar_url=avatar_url,
        voice_emotion=voice_emotion,
        ugc_image_model=ugc_image_model,
        burn_captions=do_captions,
        video_backend=video_backend,
        openrouter_video_model=openrouter_video_model,
        custom_script=custom_script,
        reference_audio_path=ref_audio_path_str,
    ))

    return {"job_id": job_id}


@app.get("/status/{job_id}")
async def status_stream(job_id: str):
    """SSE stream of pipeline progress."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        sent_count = 0
        while True:
            job   = JOBS.get(job_id, {})
            steps = job.get("steps", [])

            while sent_count < len(steps):
                step = steps[sent_count]
                yield f"data: {json.dumps(step)}\n\n"
                sent_count += 1

            status = job.get("status", "queued")
            if status in ("completed", "failed"):
                final = {
                    "step":                   status,
                    "message":                (job.get("steps") or [{}])[-1].get("message", "Done"),
                    "progress":               job.get("progress", 100),
                    "video_url":              job.get("video_url", ""),
                    "script":                 job.get("script", ""),
                    "raw_script":             job.get("raw_script", ""),
                    "display_script":         job.get("display_script", ""),
                    "audio_url":              job.get("audio_url", ""),
                    "ugc_image_url":          job.get("ugc_image_url", ""),
                    "segments":               job.get("segments", []),
                    "clip_urls":              job.get("clip_urls", []),
                    "analysis":               job.get("analysis", {}),
                    "video_backend":          job.get("video_backend", "wavespeed"),
                    "openrouter_video_model": job.get("openrouter_video_model", ""),
                    "error":                  job.get("error", ""),
                }
                yield f"data: {json.dumps(final)}\n\n"
                break

            await asyncio.sleep(1.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    job = _job(job_id)
    return {
        "job_id":                 job_id,
        "status":                 job.get("status"),
        "product_name":           job.get("product_name"),
        "video_url":              job.get("video_url", ""),
        "ugc_image_url":          job.get("ugc_image_url", ""),
        "audio_url":              job.get("audio_url", ""),
        "script":                 job.get("script", ""),
        "raw_script":             job.get("raw_script", ""),
        "display_script":         job.get("display_script", ""),
        "segments":               job.get("segments", []),
        "clip_urls":              job.get("clip_urls", []),
        "analysis":               job.get("analysis", {}),
        "video_backend":          job.get("video_backend", "wavespeed"),
        "openrouter_video_model": job.get("openrouter_video_model", ""),
        "error":                  job.get("error", ""),
        "progress":               job.get("progress", 0),
        "steps":                  job.get("steps", []),
    }


@app.get("/download/{job_id}")
async def download_video(job_id: str):
    job = JOBS.get(job_id, {})
    video_url = job.get("video_url", "")

    video_path = None
    if video_url:
        filename = Path(video_url).name
        candidate = UPLOAD_DIR / filename
        if candidate.exists():
            video_path = candidate

    if not video_path:
        matches = list(UPLOAD_DIR.glob(f"final_{job_id}*.mp4"))
        if matches:
            video_path = matches[0]

    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    brand = job.get("analysis", {}).get("brand_name", "ugc_ad") if isinstance(job.get("analysis"), dict) else "ugc_ad"
    safe_brand = "".join(c for c in brand if c.isalnum() or c in ("-", "_")).strip() or "ugc_ad"
    return FileResponse(
        path=str(video_path),
        filename=f"{safe_brand}_ad.mp4",
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{safe_brand}_ad.mp4"'}
    )


@app.get("/health/voxcpm")
async def voxcpm_health():
    try:
        data = await check_health()
        return {"status": "ok", "voxcpm": data}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "error": str(e)})


@app.get("/emotions")
async def get_emotions():
    try:
        emotions = await list_emotions()
        return {"emotions": emotions}
    except Exception:
        return {
            "emotions": [
                "hook", "explain", "key_term", "encourage",
                "excited", "quiz_question", "quiz_correct", "quiz_wrong", "neutral",
            ]
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
