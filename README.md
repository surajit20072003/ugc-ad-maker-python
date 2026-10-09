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
