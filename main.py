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
import os
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

import aiofiles  # noqa: F401
import httpx
from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from pipeline.analyze import analyze_physical_product, analyze_software_product
from pipeline.audio_proc import process_reference_audio, get_audio_duration_bytes, normalize_wav_loudness
from pipeline.image_gen import generate_ugc_prompt, generate_ugc_image, generate_broll_keyframe_prompts
from pipeline.prompt_enhancer import enhance_broll_prompt, DEFAULT_LIGHTING_ANCHOR
from pipeline.visual_sync_validator import validate_and_enforce_sync
from pipeline.script_gen import generate_script
from pipeline.script_split import parse_segments, segments_to_full_script, format_script_for_display
from pipeline.tts import generate_voiceover, list_emotions, check_health
from pipeline.upload import upload_audio_wav, upload_image_bytes
from pipeline.video_gen import generate_video
from pipeline.broll_gen import generate_kling_broll
from pipeline.scene_composer import compose_pure_broll_scene
from pipeline.infographic_broll import build_infographic_scenes
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
        extra.pop("job_id", None)
        entry = {"job_id": job_id, "step": step, "message": message, "progress": progress, "time": timestamp, **extra}
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
    tts_engine: str = "voxcpm",
    broll_video_model: str = "bytedance/seedance-1-5-pro",
    image_provider: str = "local",
    local_image_model: str = "flux-dev",
    video_provider: str = "local",
    local_video_model: str = "ltx23_distilled_q6",
    motion_style: str = "reel",
) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    job["video_backend"] = video_backend
    job["openrouter_video_model"] = openrouter_video_model
    job["tts_engine"] = tts_engine
    job["image_provider"] = image_provider
    job["local_image_model"] = local_image_model
    job["video_provider"] = video_provider
    job["local_video_model"] = local_video_model
    job["motion_style"] = motion_style


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
        # Step 3 (AUDIO-FIRST): Generate Voiceover per Segment (VoxCPM / ByteDance)
        # Sequential execution + self-anchored voice cloning to lock voice identity.
        # ────────────────────────────────────────────────────────────────────
        engine_label = "ByteDance Seed Audio" if tts_engine == "bytedance" else "VoxCPM"
        _emit(job_id, "tts", f"🎙️ [Audio-First] Generating voiceovers ({engine_label}) for {len(segments)} scenes...", 20)

        async def _gen_single_tts(idx: int, seg: dict, ref_audio: str = ""):
            label = seg.get("label", f"scene_{idx+1}")
            emotion = seg.get("emotion", "encourage")
            if ref_audio:
                emotion = "neutral"  # style prefixes shift the cloned timbre between scenes
            stype = seg.get("scene_type", "avatar")
            _emit(job_id, "tts", f"🎙️ [Scene {idx+1}/{len(segments)} - {stype.upper()}] Synthesizing speech ({engine_label})...", 20 + int((idx / len(segments)) * 15))
            wav = await generate_voiceover(
                seg["text"],
                emotion=emotion,
                reference_audio=ref_audio,
                engine=tts_engine,
            )
            dur = get_audio_duration_bytes(wav)
            seg["audio_duration_sec"] = dur
            _emit(job_id, "tts", f"✅ [Scene {idx+1}/{len(segments)}] Speech ready: {dur:.2f}s ({len(wav) // 1024} KB)", 20 + int(((idx + 1) / len(segments)) * 15))
            return wav

        # Sequential TTS — generate scene 0 first, save its output as voice anchor,
        # then pass it as reference_audio to all remaining segments to lock voice identity.
        wav_bytes_list: list[bytes] = []
        job_voice_anchor = reference_audio_path  # Start with user upload (if any)

        for i, seg in enumerate(segments):
            wav = await _gen_single_tts(i, seg, ref_audio=job_voice_anchor)
            # Normalize to EBU R128 (-16 LUFS) to ensure equal perceived loudness
            # across both WaveSpeed avatar lip-sync clips and ffmpeg b-roll clips
            wav = normalize_wav_loudness(wav)
            dur = get_audio_duration_bytes(wav)
            seg["audio_duration_sec"] = dur
            wav_bytes_list.append(wav)
            # After first segment: self-anchor — save its WAV to pin the voice for the rest
            if i == 0 and not job_voice_anchor:
                try:
                    anchor_path = UPLOAD_DIR / f"voice_anchor_{job_id}.wav"
                    anchor_path.write_bytes(wav)
                    job_voice_anchor = str(anchor_path)
                    _emit(job_id, "tts", f"🔒 Voice anchor locked from Scene 1 — remaining scenes clone this voice.", 23)
                except Exception:
                    pass  # Anchor save failure is non-fatal — continue without anchor

        total_audio_runtime = sum(s.get("audio_duration_sec", 0.0) for s in segments)
        _emit(job_id, "tts", f"🎵 All voiceovers ready. Exact total ad duration: {total_audio_runtime:.2f}s", 38)

        # Upload audio WAV files
        _emit(job_id, "upload_audio", f"Saving {len(wav_bytes_list)} audio WAV files for video muxing...", 40)
        audio_upload_tasks = [
            upload_audio_wav(wav, f"{job_id}_{i}")
            for i, wav in enumerate(wav_bytes_list)
        ]
        audio_urls: list[str] = list(await asyncio.gather(*audio_upload_tasks))
        job["audio_url"]  = audio_urls[0] if audio_urls else ""
        job["audio_urls"] = audio_urls

        # ────────────────────────────────────────────────────────────────────
        # Step 4: Generate Avatar Images (ONLY for Avatar Scenes!)
        # ────────────────────────────────────────────────────────────────────
        avatar_scene_indices = [i for i, seg in enumerate(segments) if seg.get("scene_type") == "avatar"]
        segment_image_urls: list[str] = [""] * len(segments)

        ref_image_url = product_image_url
        if not ref_image_url and product_image_bytes:
            _emit(job_id, "upload_product", "Uploading product reference...", 43)
            ref_image_url = await upload_image_bytes(product_image_bytes, job_id)

        if avatar_url:
            _emit(job_id, "image_gen", f"Using custom creator avatar for avatar scenes...", 45)
            for i in avatar_scene_indices:
                segment_image_urls[i] = avatar_url
        elif avatar_scene_indices:
            _emit(job_id, "image_gen",
                  f"Rendering photorealistic creator poses for {len(avatar_scene_indices)} avatar scenes...", 45)

            async def _gen_single_avatar_img(i: int):
                seg = segments[i]
                prompt = await generate_ugc_prompt(
                    product_name, analysis,
                    mode=product_mode,
                    segment=seg["label"],
                    scene_direction=seg.get("scene_direction"),
                )
                img_url = await generate_ugc_image(
                    prompt,
                    ref_image_url,
                    model=ugc_image_model,
                    job_id=f"{job_id}_{i}",
                    image_provider=image_provider,
                    local_image_model=local_image_model,
                )
                return i, img_url

            img_tasks = [_gen_single_avatar_img(i) for i in avatar_scene_indices]
            img_results = await asyncio.gather(*img_tasks)
            for idx_val, img_val in img_results:
                segment_image_urls[idx_val] = img_val

        job["ugc_image_url"] = segment_image_urls[0] if segment_image_urls and segment_image_urls[0] else ""
        job["segment_image_urls"] = segment_image_urls

        # ────────────────────────────────────────────────────────────────────
        # Step 5: Generate Hybrid Video Clips (WaveSpeed/HeyGen Avatar + Kling B-Roll)
        # ────────────────────────────────────────────────────────────────────
        _emit(job_id, "video", f"Generating {len(segments)} cinematic hybrid scenes...", 55)

        # Build job-level lighting anchor from brand colors for visual coherence across all beats
        color_scheme = analysis.get("color_scheme", [])
        brand_color_name = color_scheme[0].get("name", "neutral") if color_scheme else "neutral"
        job_lighting_anchor = (
            f"Softbox key light from upper-left at 45 degrees, warm white 5500K. "
            f"Subtle diffused fill light from right. "
            f"Deep neutral dark background. Brand accent: {brand_color_name} tones in product. "
            "No lens flare. No distracting patterns."
        )

        # Infographic image-to-video B-roll (storyboard -> keyframes -> Veo -> voice-muxed scene).
        # Runs in the background while avatar scenes render; scenes it can't finish fall back to the legacy path.
        use_infog = os.getenv("INFOGRAPHIC_BROLL", "1") != "0" and any(
            sg.get("scene_type") == "b_roll" for sg in segments
        )

        async def _run_infographic() -> dict:
            try:
                return await build_infographic_scenes(
                    job_id=job_id,
                    segments=segments,
                    analysis=analysis,
                    product_name=product_name,
                    mode=product_mode,
                    product_image_url=ref_image_url,
                    on_log=lambda m: _emit(job_id, "video", m, 60),
                    image_model=ugc_image_model,
                    video_model=broll_video_model,
                    video_provider=video_provider,
                    local_video_model=local_video_model,
                    image_provider=image_provider,
                    local_image_model=local_image_model,
                )
            except Exception as infog_err:
                _emit(job_id, "video", f"⚠️ Infographic B-roll failed ({infog_err}); using legacy B-roll.", 60)
                return {}


        infog_task = asyncio.create_task(_run_infographic()) if use_infog else None

        # Legacy path: pre-enhance B-roll scenes sequentially to carry forward continuity (previous_end_hint)
        # and validate voiceover-to-visual literal sync
        broll_enhancements: dict[int, dict] = {}
        last_broll_end_hint = ""
        for b_idx, b_seg in (enumerate(segments) if not use_infog else []):
            if b_seg.get("scene_type") == "b_roll":
                b_dur = b_seg.get("audio_duration_sec", 5.0)
                _emit(job_id, "video", f"✨ [Scene {b_idx+1} B-Roll] Enhancing prompts (voiceover-sync & lighting continuity)...", 54)
                try:
                    scene_dir = b_seg.get("scene_direction", {})
                    if scene_dir.get("kling_prompt_start"):
                        raw = (
                            f"START: {scene_dir['kling_prompt_start']} | "
                            f"END: {scene_dir.get('kling_prompt_end', '')} | "
                            f"MOTION: {scene_dir.get('kling_motion_prompt', '')}"
                        )
                    else:
                        raw = b_seg.get("kling_prompt") or b_seg.get("scene_prompt") or ""

                    enhanced = await enhance_broll_prompt(
                        voiceover_text=b_seg["text"],
                        raw_prompt=raw,
                        product_name=product_name,
                        analysis=analysis,
                        mode=product_mode,
                        target_duration_sec=b_dur,
                        lighting_anchor=job_lighting_anchor,
                        previous_end_hint=last_broll_end_hint,
                    )
                    _emit(job_id, "video", f"📐 [Scene {b_idx+1} B-Roll] AI reasoning: {enhanced.get('visual_reasoning', '')[:100]}...", 54)
                    val_prompts = validate_and_enforce_sync(
                        keyframe_prompts={
                            "start_prompt":        enhanced["start_frame_prompt"],
                            "end_prompt":          enhanced["end_frame_prompt"],
                            "video_motion_prompt": enhanced["motion_prompt"],
                        },
                        voiceover_text=b_seg["text"],
                        mode=product_mode,
                    )
                    broll_enhancements[b_idx] = val_prompts
                    last_broll_end_hint = val_prompts.get("end_prompt", "")
                except Exception as enhance_err:
                    _emit(job_id, "video", f"⚠️ [Scene {b_idx+1}] Enhancer fallback: {enhance_err}", 54)
                    fb_prompts = await generate_broll_keyframe_prompts(
                        product_name=product_name,
                        analysis=analysis,
                        segment=b_seg,
                        mode=product_mode,
                        lighting_anchor=job_lighting_anchor,
                        previous_end_prompt=last_broll_end_hint,
                    )
                    val_fb = validate_and_enforce_sync(
                        keyframe_prompts=fb_prompts,
                        voiceover_text=b_seg["text"],
                        mode=product_mode,
                    )
                    broll_enhancements[b_idx] = val_fb
                    last_broll_end_hint = val_fb.get("end_prompt", "")

        async def _gen_single_hybrid_scene(idx: int, seg: dict):
            label = seg.get("label", f"scene_{idx+1}")
            stype = seg.get("scene_type", "avatar")
            dur = seg.get("audio_duration_sec", 5.0)
            pct_base = 55 + int((idx / len(segments)) * 32)

            def _log_cb(msg: str):
                _emit(job_id, "video", f"[Scene {idx+1}/{len(segments)} {stype.upper()}] {msg}", pct_base)

            if stype == "b_roll":
                if infog_task is not None:
                    infog_res = await infog_task
                    if idx in infog_res:
                        _emit(job_id, "video", f"✅ Scene {idx+1} infographic B-roll ready ({dur:.2f}s)", pct_base + int(32 / len(segments)))
                        return infog_res[idx]
                # High-Fidelity Image-to-Video B-Roll (legacy path):
                keyframe_prompts = broll_enhancements.get(idx)
                if not keyframe_prompts:
                    keyframe_prompts = await generate_broll_keyframe_prompts(
                        product_name=product_name,
                        analysis=analysis,
                        segment=seg,
                        mode=product_mode,
                        lighting_anchor=job_lighting_anchor,
                    )
                    keyframe_prompts = validate_and_enforce_sync(keyframe_prompts, seg["text"], mode=product_mode)


                # 2. Render Start and End keyframe images using Nano Banana Pro (google/gemini-3-pro-image)
                _emit(job_id, "video", f"🖼️ [Scene {idx+1} B-Roll] Rendering photorealistic Start & End frames (Nano Banana Pro)...", pct_base)
                start_img_url, end_img_url = await asyncio.gather(
                    generate_ugc_image(
                        ugc_prompt=keyframe_prompts["start_prompt"],
                        product_image_url=ref_image_url,
                        model=ugc_image_model,
                        job_id=f"{job_id}_broll_start_{idx}",
                        image_provider=image_provider,
                        local_image_model=local_image_model,
                    ),
                    generate_ugc_image(
                        ugc_prompt=keyframe_prompts["end_prompt"],
                        product_image_url=ref_image_url,
                        model=ugc_image_model,
                        job_id=f"{job_id}_broll_end_{idx}",
                        image_provider=image_provider,
                        local_image_model=local_image_model,
                    ),
                )

                # 3. Animate 9:16 video between Start & End keyframes
                _emit(job_id, "video", f"🎬 [Scene {idx+1} B-Roll] Generating I2V video from keyframes ({video_provider.upper()}, {dur:.2f}s target)...", pct_base)
                broll_raw_url = await generate_kling_broll(
                    prompt=keyframe_prompts["video_motion_prompt"],
                    target_duration_sec=dur,
                    segment_label=label,
                    first_frame_url=start_img_url,
                    last_frame_url=end_img_url,
                    model=broll_video_model or "google/veo-3.1-fast",
                    on_log=_log_cb,
                    video_provider=video_provider,
                    local_video_model=local_video_model,
                )


                # Precision-mux B-Roll video with scene voiceover
                local_broll = UPLOAD_DIR / f"broll_raw_{job_id}_{idx}.mp4"
                local_audio = UPLOAD_DIR / f"audio_{job_id}_{idx}.wav"
                local_audio.write_bytes(wav_bytes_list[idx])

                filename = broll_raw_url.split("/")[-1].split("?")[0]
                existing_file = UPLOAD_DIR / filename
                if existing_file.exists():
                    local_broll = existing_file
                else:
                    async with httpx.AsyncClient(timeout=120) as client:
                        resp = await client.get(broll_raw_url)
                        resp.raise_for_status()
                        local_broll.write_bytes(resp.content)

                muxed_filename = f"broll_muxed_{job_id}_{idx}.mp4"
                muxed_path = UPLOAD_DIR / muxed_filename
                compose_pure_broll_scene(
                    video_path=local_broll,
                    audio_path=local_audio,
                    output_path=muxed_path,
                    target_duration=dur,
                )

                server_base = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")
                final_scene_url = f"{server_base}/uploads/{muxed_filename}"
                _emit(job_id, "video", f"✅ Scene {idx+1} I2V B-Roll synced with voice ({dur:.2f}s)", pct_base + int(32 / len(segments)))
                return final_scene_url

            else:
                # Talking Head Avatar scene
                _emit(job_id, "video", f"👤 Generating Creator Avatar for Scene {idx+1} ({label})...", pct_base)
                avatar_img = segment_image_urls[idx] or avatar_url or ref_image_url
                clip = await generate_video(
                    image_url=avatar_img,
                    audio_url=audio_urls[idx] if idx < len(audio_urls) else "",
                    script=seg["text"],
                    segment=seg["label"],
                    resolution="720p",
                    backend=video_backend,
                    openrouter_model=openrouter_video_model,
                    scene_prompt=seg.get("scene_prompt", ""),
                    on_log=_log_cb,
                )
                _emit(job_id, "video", f"✅ Scene {idx+1} Avatar clip ready!", pct_base + int(32 / len(segments)))
                return clip

        video_tasks = [_gen_single_hybrid_scene(i, seg) for i, seg in enumerate(segments)]
        clip_urls: list[str] = list(await asyncio.gather(*video_tasks))
        job["clip_urls"] = clip_urls

        # ────────────────────────────────────────────────────────────────────
        # Step 6: Compose Final Video (Stitching + Glassmorphism Icon Cards)
        # ────────────────────────────────────────────────────────────────────
        _emit(job_id, "compose",
              f"Stitching {len(clip_urls)} hybrid clips + rendering animated glassmorphism icon cards (ffmpeg)...", 90)

        # Extract brand accent color from analysis if available
        brand_color_tuple = None
        color_scheme = analysis.get("color_scheme", [])
        if color_scheme and isinstance(color_scheme, list):
            hex_c = color_scheme[0].get("hex", "")
            if hex_c and len(hex_c) == 7 and hex_c.startswith("#"):
                try:
                    brand_color_tuple = (int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16))
                except ValueError:
                    pass

        if len(clip_urls) == 1:
            video_url = await save_single_clip(
                clip_url=clip_urls[0],
                segments=segments,
                job_id=job_id,
                burn_captions=burn_captions,
                audio_urls=audio_urls,
                brand_color=brand_color_tuple,
                motion_style=motion_style,
            )
        else:
            video_url = await compose_final_video(
                clip_urls=clip_urls,
                segments=segments,
                job_id=job_id,
                burn_captions=burn_captions,
                audio_urls=audio_urls,
                brand_color=brand_color_tuple,
                motion_style=motion_style,
            )


        job["video_url"] = video_url

        # ────────────────────────────────────────────────────────────────────
        # Done — mark completed BEFORE emitting done event so /result/ is ready
        # ────────────────────────────────────────────────────────────────────
        job["status"] = "completed"
        try:
            _emit(
                job_id, "done", "Your UGC ad is ready!", 100,
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
        except Exception as emit_err:
            print(f"[{job_id[:8]}] Warning emitting done event: {emit_err}", flush=True)

    except Exception as exc:
        _bg = locals().get("infog_task")
        if _bg is not None and not _bg.done():
            _bg.cancel()
        if job.get("video_url"):
            # Video was already composed successfully
            job["status"] = "completed"
            print(f"[{job_id[:8]}] Pipeline completed with post-processing notice: {exc}", flush=True)
        else:
            _emit(job_id, "error", f"Error: {exc}", job.get("progress", 0))
            job["status"] = "failed"
            job["error"]  = str(exc)


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/gpu-status")
async def get_gpu_status():
    """Live GPU server health and status check."""
    try:
        from pipeline.local_gpu_client import LocalGPUClient
        client = LocalGPUClient()
        available = client.is_available()
        return {
            "available": available,
            "url": client.base_url,
            "models": {
                "image": ["flux-dev", "flux-schnell", "flux-1.1-pro"],
                "video": ["ltx23_distilled_q6", "ltx21"],
            }
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


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
    image_provider:         str            = Form("local"),
    local_image_model:      str            = Form("flux-dev"),
    ugc_image_model:        str            = Form("openai/gpt-image-2"),
    video_provider:         str            = Form("local"),
    local_video_model:      str            = Form("ltx23_distilled_q6"),
    broll_video_model:      str            = Form("bytedance/seedance-1-5-pro"),
    motion_style:           str            = Form("reel"),
    avatar_url:             str            = Form(""),
    burn_captions:          str            = Form("false"),
    video_backend:          str            = Form("wavespeed"),
    openrouter_video_model: str            = Form("google/veo-3.1-fast"),
    custom_script:          str            = Form(""),
    tts_engine:             str            = Form("voxcpm"),
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

    do_captions = burn_captions.lower() in ("true", "1", "yes")

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
        "tts_engine":             tts_engine,
        "image_provider":         image_provider,
        "local_image_model":      local_image_model,
        "video_provider":         video_provider,
        "local_video_model":      local_video_model,
        "motion_style":           motion_style,
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
        tts_engine=tts_engine,
        broll_video_model=broll_video_model,
        image_provider=image_provider,
        local_image_model=local_image_model,
        video_provider=video_provider,
        local_video_model=local_video_model,
        motion_style=motion_style,
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
                    "tts_engine":             job.get("tts_engine", "voxcpm"),
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
    job = JOBS.get(job_id)
    if not job:
        # Check if video exists on disk from previous completed run or service restart
        matches = list(UPLOAD_DIR.glob(f"final_{job_id}*.mp4"))
        if matches:
            return {
                "job_id": job_id,
                "status": "completed",
                "video_url": f"/static/uploads/{matches[0].name}",
                "progress": 100,
                "steps": [],
            }
        raise HTTPException(status_code=404, detail="Job not found")

    video_url = job.get("video_url", "")
    if not video_url:
        matches = list(UPLOAD_DIR.glob(f"final_{job_id}*.mp4"))
        if matches:
            video_url = f"/static/uploads/{matches[0].name}"
            job["video_url"] = video_url
            job["status"] = "completed"
            job["progress"] = 100
            job["error"] = None
    elif job.get("status") != "completed":
        job["status"] = "completed"
        job["progress"] = 100
        job["error"] = None
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
        "tts_engine":             job.get("tts_engine", "voxcpm"),
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
