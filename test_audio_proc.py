import sys, os
sys.path.insert(0, '.')
from pipeline.audio_proc import process_reference_audio
from pathlib import Path

Path("dummy.wav").write_bytes(b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00')
process_reference_audio(Path("dummy.wav"), Path("dummy_out.wav"))
print("Done audio_proc", Path("dummy_out.wav").exists())
