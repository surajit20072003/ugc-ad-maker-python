import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from pipeline.scene_composer import compose_pure_broll_scene
from pipeline.video_compose import compose_final_video

JOB_ID = "04a7bec4-8f52-4a3b-8752-a9953f3a4bea"
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")
UPLOAD_DIR = Path("uploads")

# Already downloaded clips
HOOK_CLIP  = UPLOAD_DIR / "openrouter_clip_gen-vid-1791638155-ZSo3sacMLVQrvx0eGNA1.mp4"
CTA_CLIP   = UPLOAD_DIR / "openrouter_clip_gen-vid-1791638154-o99qB0qjuP07KBTca61O.mp4"

# Raw Kling brolls (scene order: scene_2=idx1, scene_3=idx2, scene_4=idx3)
BROLL_RAW = {
    1: UPLOAD_DIR / "broll_gen-vid-1791638154-Kj0gTRLSwicPACiCjEIA.mp4",  # scene_2
    2: UPLOAD_DIR / "broll_gen-vid-1791638154-dgdn0oXyLnJtjw9GFgIQ.mp4",  # scene_3
    3: UPLOAD_DIR / "broll_gen-vid-1791638154-u3vdeRBwIi7wW2fR5OnC.mp4",  # scene_4
}

AUDIO_DUR = {1: 5.92, 2: 7.84, 3: 6.72}
AUDIO_FILES = {i: UPLOAD_DIR / f"audio_{JOB_ID}_{i}.wav" for i in range(5)}

SEGMENTS = [
    {"label": "hook",   "text": '"Why should I spend more on a website? Someone else said they\'ll make it cheaper." Fair question.', "scene_type": "avatar",  "audio_duration_sec": 5.60},
    {"label": "scene_2","text": "But ask yourself: Are you buying a few webpages — or building your business presence online?",             "scene_type": "b_roll",  "audio_duration_sec": 5.92},
    {"label": "scene_3","text": "Slow loading. Poor mobile experience. Weak security. Confusing design. Your customer notices these things.", "scene_type": "b_roll",  "audio_duration_sec": 7.84},
    {"label": "scene_4","text": "A professional website should be fast, secure, mobile-friendly, easy to understand and built to support your business.", "scene_type": "b_roll", "audio_duration_sec": 6.72},
    {"label": "cta",    "text": "Don't choose your website only by price. Choose what your customer will experience. ROI Infotech — 15+ Years | 649 Websites Designed roiinfotech.com", "scene_type": "avatar", "audio_duration_sec": 13.92},
]

# Step 1: Precision-mux brolls with their voiceover audio
muxed = {}
for idx in [1, 2, 3]:
    raw    = BROLL_RAW[idx]
    audio  = AUDIO_FILES[idx]
    dur    = AUDIO_DUR[idx]
    out    = UPLOAD_DIR / f"broll_muxed_{JOB_ID}_{idx}.mp4"
    print(f"[Mux] Scene {idx+1} broll -> {out.name}  (dur={dur}s)")
    compose_pure_broll_scene(video_path=raw, audio_path=audio, output_path=out, target_duration=dur)
    muxed[idx] = out
    print(f"  Done: {out.stat().st_size//1024} KB")

# Step 2: Build clip_url list
clip_urls = [
    f"{SERVER_URL}/uploads/{HOOK_CLIP.name}",
    f"{SERVER_URL}/uploads/{muxed[1].name}",
    f"{SERVER_URL}/uploads/{muxed[2].name}",
    f"{SERVER_URL}/uploads/{muxed[3].name}",
    f"{SERVER_URL}/uploads/{CTA_CLIP.name}",
]
audio_urls = [f"{SERVER_URL}/uploads/{AUDIO_FILES[i].name}" for i in range(5)]

print("\n[Stitch] Composing final video with glassmorphic icon overlays...")
async def go():
    url = await compose_final_video(
        clip_urls=clip_urls,
        segments=SEGMENTS,
        job_id=JOB_ID,
        burn_captions=False,
        audio_urls=audio_urls,
        brand_color=(37, 99, 235),  # ROI Infotech Tech Blue #2563EB
    )
    print(f"\nFINAL VIDEO READY: {url}")
    return url

if __name__ == "__main__":
    asyncio.run(go())
