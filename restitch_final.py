"""
restitch_final.py
─────────────────
Re-stitches the 5 already-rendered clips with the new sleek floating pill badges
in the upper-right corner (zero face obstruction).
Takes ~10 seconds with local FFmpeg, zero API credits needed!
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from pipeline.video_compose import compose_final_video

JOB_ID = "3f2d9d16-3999-4025-9a98-b42ba3924cda"
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")
UPLOAD_DIR = Path("uploads")

CLIP_URLS = [
    f"{SERVER_URL}/uploads/openrouter_clip_gen-vid-1791546218-O5rvGdv3YQnZANDoACSb.mp4",
    f"{SERVER_URL}/uploads/broll_muxed_{JOB_ID}_1.mp4",
    f"{SERVER_URL}/uploads/broll_muxed_{JOB_ID}_2.mp4",
    f"{SERVER_URL}/uploads/broll_muxed_{JOB_ID}_3.mp4",
    f"{SERVER_URL}/uploads/openrouter_clip_gen-vid-1791546218-feM4RKZdKSOAUBfDXhsq.mp4",
]

AUDIO_URLS = [
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_0.wav",
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_1.wav",
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_2.wav",
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_3.wav",
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_4.wav",
]

SEGMENTS = [
    {"label": "hook", "text": "Why should I spend more on a website? Someone else said they'll make it cheaper. Fair question.", "scene_type": "avatar", "audio_duration_sec": 6.56},
    {"label": "scene_2", "text": "But ask yourself: Are you buying a few webpages — or building your business presence online?", "scene_type": "b_roll", "audio_duration_sec": 6.88},
    {"label": "scene_3", "text": "Slow loading. Poor mobile experience. Weak security. Confusing design. Your customer notices these things.", "scene_type": "b_roll", "audio_duration_sec": 9.60},
    {"label": "scene_4", "text": "A professional website should be fast, secure, mobile-friendly, easy to understand and built to support your business.", "scene_type": "b_roll", "audio_duration_sec": 7.84},
    {"label": "cta", "text": "Don't choose your website only by price. Choose what your customer will experience. ROI Infotech — 15+ Years | 649 Websites Designed roiinfotech.com", "scene_type": "avatar", "audio_duration_sec": 15.52},
]


async def main():
    print("🎬 Re-stitching final video with new upper-right floating glass pill badges...")
    video_url = await compose_final_video(
        clip_urls=CLIP_URLS,
        segments=SEGMENTS,
        job_id=JOB_ID,
        burn_captions=False,
        audio_urls=AUDIO_URLS,
        brand_color=(59, 130, 246),  # Electric blue
    )
    print(f"\n🎉 DONE! Updated video ready: {video_url}")


if __name__ == "__main__":
    asyncio.run(main())
