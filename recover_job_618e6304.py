"""
recover_job_618e6304.py
───────────────────────
Complete the failed job (618e6304-fba4-46b5-a404-2efcee667db4) without any additional cloud cost:
1. Renders the only missing scene (Scene 2 B-roll) completely on Local GPU (Flux Schnell + LTX-Video 2.3).
2. Muxes with existing voiceover audio.
3. Stitches all 5 scenes together with kinetic subtitles, 35mm film grain, and comic burst transitions.
4. Produces the final ad video at uploads/final_618e6304-fba4-46b5-a404-2efcee667db4.mp4.
"""
import asyncio
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from pipeline.local_gpu_client import LocalGPUClient, generate_image_async, generate_i2v_async
from pipeline.video_compose import compose_final_video

JOB_ID = "618e6304-fba4-46b5-a404-2efcee667db4"
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8765").rstrip("/")
UPLOAD_DIR = Path("uploads")

SEGMENTS = [
    {
        "label": "hook",
        "text": "Are you relying only on Instagram and LinkedIn for your business? Social media is rented land. When the algorithm changes, your reach disappears overnight.",
        "emotion": "hook",
        "scene_type": "avatar",
        "audio_duration_sec": 12.539,
    },
    {
        "label": "scene_2",
        "text": "When a serious customer wants to hire you, they don't scroll your feed. They search Google for your website to see if you're a legitimate business.",
        "emotion": "explain",
        "scene_type": "b_roll",
        "audio_duration_sec": 8.359,
    },
    {
        "label": "scene_3",
        "text": "Slow loading, weak mobile experience, or no website at all immediately loses customer trust. A fast, modern site builds instant authority.",
        "emotion": "encourage",
        "scene_type": "b_roll",
        "audio_duration_sec": 11.598,
    },
    {
        "label": "scene_4",
        "text": "Your website is your best 24/7 employee. It presents your work clearly, answers questions, and captures qualified inquiries around the clock.",
        "emotion": "encourage",
        "scene_type": "b_roll",
        "audio_duration_sec": 9.143,
    },
    {
        "label": "cta",
        "text": "Stop losing deals to competitors. Build your business presence with ROI Infotech. Over 15 years of experience and 649 websites delivered. Visit roiinfotech.com or call +91 99453 79333.",
        "emotion": "excited",
        "scene_type": "avatar",
        "audio_duration_sec": 16.144,
    },
]

AUDIO_URLS = [
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_0.wav",
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_1.wav",
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_2.wav",
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_3.wav",
    f"{SERVER_URL}/uploads/audio_{JOB_ID}_4.wav",
]


async def ensure_scene_2_broll() -> str:
    """Render Scene 2 B-roll using Local GPU at $0 cost."""
    muxed_path = UPLOAD_DIR / f"broll_muxed_{JOB_ID}_1.mp4"
    if muxed_path.exists() and muxed_path.stat().st_size > 100_000:
        print(f"✅ Scene 2 B-roll already rendered: {muxed_path}")
        return f"{SERVER_URL}/uploads/{muxed_path.name}"

    raw_path = UPLOAD_DIR / f"broll_raw_{JOB_ID}_1.mp4"
    audio_path = UPLOAD_DIR / f"audio_{JOB_ID}_1.wav"

    if not raw_path.exists() or raw_path.stat().st_size < 100_000:
        print("🖥️ Step 1/3: Rendering Scene 2 keyframe on Local GPU (Flux)...")
        client = LocalGPUClient()
        if not client.is_available():
            raise RuntimeError("Local GPU server is not reachable!")

        start_img_path = UPLOAD_DIR / f"local_scene2_{JOB_ID}_start.jpg"
        if not start_img_path.exists():
            img_res = await generate_image_async(
                client=client,
                prompt="Clean top-down view of modern sleek smartphone displaying Google search engine with inquiry for professional web agency, sharp vector UI, minimalist tech office desk, photorealistic, vertical 9:16",
                output_path=str(start_img_path),
                model="flux_dev",
            )
            print(f"✅ Scene 2 start frame ready: {img_res}")

        print("🎬 Step 2/3: Generating Scene 2 video on Local GPU (LTX-Video 2.3)...")
        vid_res = await generate_i2v_async(
            client=client,
            prompt="Locked static camera. Smooth video. Hand holding smartphone searching on Google for business website, results appearing cleanly on screen, 4k, vertical 9:16",
            image_path=str(start_img_path),
            image_path_end=None,
            duration=8.36,
            output_path=str(raw_path),
            model="ltx23_distilled_q6",
        )
        print(f"✅ Scene 2 raw video ready: {vid_res}")

    print("🎵 Step 3/3: Precision muxing Scene 2 video with voiceover...")
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(raw_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-t", "8.359",
        "-shortest",
        "-pix_fmt", "yuv420p",
        str(muxed_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"✅ Scene 2 B-roll fully assembled: {muxed_path}")
    return f"{SERVER_URL}/uploads/{muxed_path.name}"


async def main():
    print(f"🚀 Recovering failed job {JOB_ID}...")
    scene_2_url = await ensure_scene_2_broll()

    clip_urls = [
        f"{SERVER_URL}/uploads/avatar_iv_gen-vid-1791874694-C22j0obyplGyK3lEHr65.mp4",
        scene_2_url,
        f"{SERVER_URL}/uploads/broll_muxed_{JOB_ID}_2.mp4",
        f"{SERVER_URL}/uploads/broll_muxed_{JOB_ID}_3.mp4",
        f"{SERVER_URL}/uploads/avatar_iv_gen-vid-1791874695-NmqoL5G2tTsO24KMidHH.mp4",
    ]

    print("\n🎞️ Stitching all 5 scenes with Reel Kinetic Subtitles + Film Texture...")
    final_url = await compose_final_video(
        clip_urls=clip_urls,
        segments=SEGMENTS,
        job_id=JOB_ID,
        burn_captions=True,
        audio_urls=AUDIO_URLS,
        brand_color=(59, 130, 246),
        motion_style="reel",
    )

    print(f"\n🎉 SUCCESS! Complete Final UGC Ad is ready:")
    print(f"👉 URL: {final_url}")
    print(f"👉 Local Path: uploads/final_{JOB_ID}.mp4")


if __name__ == "__main__":
    asyncio.run(main())
