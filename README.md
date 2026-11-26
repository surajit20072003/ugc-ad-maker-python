# UGC Ad Maker (Python)

AI-powered User-Generated Content (UGC) ad video creation platform with script generation, voiceover/TTS, image generation, and video composition.

## Features
- **Product Analysis**: Analyzes product info and images to determine audience, benefits, and style.
- **Script Generation**: Generates hook, problem, solution, and CTA scripts.
- **Voiceover / TTS**: Generates audio voiceovers using VoxCPM or configured TTS engine.
- **Visuals & Image Generation**: Generates contextual image assets (e.g. FLUX, GPT-image, Gemini).
- **Video Composition**: Compiles voiceover and video scenes with smooth transitions, audio normalization, and lip-sync options (WaveSpeed / OpenRouter).
- **Web Interface**: Fast, responsive FastAPI + HTML/JS interactive dashboard.

## Requirements
- Python 3.10+
- FFmpeg (for video and audio processing)

## Installation

1. Clone repository:
```bash
git clone <your-repo-url>
cd ugc-ad-maker-python
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Setup environment variables:
```bash
cp .env.example .env
```
Edit `.env` and fill in your API keys (`OPENROUTER_API_KEY`, etc.).

## Configuration notes
- **Required:** `OPENROUTER_API_KEY`. Everything else in `.env.example` is optional or has a default.
- `VOXCPM_URL` / `LOCAL_GPU_URL` (with their `*_API_KEY`) point at the companion `voxcpm-api` and `wan2gp-api` servers.
- `SERVER_URL` must be the address under which external services can reach **this** app (they fetch generated
  audio/images/videos from `/uploads/...`).
- **There is no authentication on the web app or API, and every ad spends your OpenRouter credits.** Keep it on a
  private network or behind a firewall / authenticating reverse proxy.
- `start.sh` runs uvicorn with `--reload` (development). For production use the systemd unit
  `ugc-ad-maker.service` (edit its paths and user first, then `sudo cp` it to `/etc/systemd/system/`).

## Running the Application

Start the web server:
```bash
./start.sh
```
Or directly with uvicorn:
```bash
uvicorn main:app --host 0.0.0.0 --port 8765 --reload
```

Then open your browser at: `http://localhost:8765`
