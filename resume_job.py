"""
resume_job.py
─────────────
Resumes job 3f2d9d16-3999-4025-9a98-b42ba3924cda:
- Reuses already completed Scene 1 & Scene 5 Avatar clips (Zero avatar cost!)
- Reuses all 5 VoxCPM audio tracks
- Generates only the 3 Kling B-roll clips (Scenes 2, 3, 4) via pure text-to-video
- Precision-muxes Kling clips to match exact speech durations
- Concat and overlays glassmorphism icon cards into final MP4
"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from pipeline.broll_gen import generate_kling_broll
from pipeline.scene_composer import compose_pure_broll_scene
from pipeline.video_compose import compose_final_video

JOB_ID = "3f2d9d16-3999-4025-9a98-b42ba3924cda"
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")
UPLOAD_DIR = Path("uploads")

# Existing completed assets
AUDIO_FILES = [
    UPLOAD_DIR / f"audio_{JOB_ID}_0.wav",  # Scene 1: 6.56s
    UPLOAD_DIR / f"audio_{JOB_ID}_1.wav",  # Scene 2: 6.88s
    UPLOAD_DIR / f"audio_{JOB_ID}_2.wav",  # Scene 3: 9.60s
    UPLOAD_DIR / f"audio_{JOB_ID}_3.wav",  # Scene 4: 7.84s
    UPLOAD_DIR / f"audio_{JOB_ID}_4.wav",  # Scene 5: 15.52s
]

SCENE_1_AVATAR = f"{SERVER_URL}/uploads/openrouter_clip_gen-vid-1791546218-O5rvGdv3YQnZANDoACSb.mp4"
SCENE_5_AVATAR = f"{SERVER_URL}/uploads/openrouter_clip_gen-vid-1791546218-feM4RKZdKSOAUBfDXhsq.mp4"

BROLL_SCENES = [
    {
        "idx": 1,
        "label": "scene_2",
        "dur": 6.88,
        "prompt": "Cinematic close-up macro glide across a sleek MacBook display showing high-converting modern website layout, fluid scrolling, glowing neon reflections on dark wood desk, 4k vertical 9:16 format, photorealistic texture",
        "text": "But ask yourself: Are you buying a few webpages — or building your business presence online?",
    },
    {
        "idx": 2,
        "label": "scene_3",
        "dur": 9.60,
        "prompt": "Cinematic macro shot of smartphone and laptop display, comparing laggy loading with instant fluid responsive website UI navigation, glowing security lock icon, dramatic lighting, 4k vertical 9:16",
        "text": "Slow loading. Poor mobile experience. Weak security. Confusing design. Your customer notices these things.",
    },
    {
        "idx": 3,
        "label": "scene_4",
        "dur": 7.84,
        "prompt": "Cinematic camera push-in on ultra fast professional business website dashboard, responsive mobile tablet and desktop, dramatic soft studio lighting, 4k vertical 9:16, photorealistic",
        "text": "A professional website should be fast, secure, mobile-friendly, easy to understand and built to support your business.",
    },
]

SEGMENTS = [
    {"label": "hook", "text": "Why should I spend more on a website? Someone else said they'll make it cheaper. Fair question.", "scene_type": "avatar", "audio_duration_sec": 6.56},
    {"label": "scene_2", "text": "But ask yourself: Are you buying a few webpages — or building your business presence online?", "scene_type": "b_roll", "audio_duration_sec": 6.88},
    {"label": "scene_3", "text": "Slow loading. Poor mobile experience. Weak security. Confusing design. Your customer notices these things.", "scene_type": "b_roll", "audio_duration_sec": 9.60},
    {"label": "scene_4", "text": "A professional website should be fast, secure, mobile-friendly, easy to understand and built to support your business.", "scene_type": "b_roll", "audio_duration_sec": 7.84},
    {"label": "cta", "text": "Don't choose your website only by price. Choose what your customer will experience. ROI Infotech — 15+ Years | 649 Websites Designed roiinfotech.com", "scene_type": "avatar", "audio_duration_sec": 15.52},
]


async def run_resume():
    print("=" * 60)
    print(f"🎬 Resuming Job {JOB_ID}")
    print("✓ Reusing Scene 1 Avatar clip (already rendered)")
    print("✓ Reusing Scene 5 Avatar clip (already rendered)")
    print("✓ Reusing all 5 VoxCPM audio files")
    print("=" * 60)

    clip_urls = [None] * 5
    clip_urls[0] = SCENE_1_AVATAR
    clip_urls[4] = SCENE_5_AVATAR

    # Generate 3 Cinematic B-roll clips in parallel
    async def _gen_broll(b):
        idx = b["idx"]
        dur = b["dur"]
        lbl = b["label"]
        print(f"\n[Scene {idx+1}/5 B_ROLL] Generating Cinematic B-roll ({dur:.2f}s target)...")
        raw_broll_url = await generate_kling_broll(
            prompt=b["prompt"],
            target_duration_sec=dur,
            segment_label=lbl,
            model="google/veo-3.1-fast",
            on_log=lambda msg: print(f"  [Scene {idx+1}] {msg}"),
        )
        print(f"  ✓ Raw B-roll clip ready: {raw_broll_url}")

        # Locate downloaded clip locally in uploads/
        broll_fname = Path(raw_broll_url).name
        local_broll = UPLOAD_DIR / broll_fname
        if not local_broll.exists():
            import httpx
            async with httpx.AsyncClient(timeout=120) as client:
                res = await client.get(raw_broll_url)
                res.raise_for_status()
                local_broll.write_bytes(res.content)

        # Precision-mux with exact audio duration
        muxed_filename = f"broll_muxed_{JOB_ID}_{idx}.mp4"
        muxed_path = UPLOAD_DIR / muxed_filename
        compose_pure_broll_scene(
            video_path=local_broll,
            audio_path=AUDIO_FILES[idx],
            output_path=muxed_path,
            target_duration=dur,
        )
        final_url = f"{SERVER_URL}/uploads/{muxed_filename}"
        print(f"  ✓ Precision-muxed Scene {idx+1} with voice: {final_url}")
        clip_urls[idx] = final_url
        return final_url

    tasks = [_gen_broll(b) for b in BROLL_SCENES]
    await asyncio.gather(*tasks)

    print("\n" + "=" * 60)
    print("🎬 All 5 clips ready! Stitching and adding glassmorphic icon cards...")
    for i, c in enumerate(clip_urls):
        print(f"  Clip {i+1}: {c}")

    audio_urls = [f"{SERVER_URL}/uploads/{f.name}" for f in AUDIO_FILES]
    final_video_url = await compose_final_video(
        clip_urls=clip_urls,
        segments=SEGMENTS,
        job_id=JOB_ID,
        burn_captions=False,
        audio_urls=audio_urls,
        brand_color=(59, 130, 246),  # Electric blue for ROI Infotech
    )

    print("=" * 60)
    print(f"🎉 FINAL VIDEO READY: {final_video_url}")
    print("=" * 60)
    return final_video_url


if __name__ == "__main__":
    asyncio.run(run_resume())
