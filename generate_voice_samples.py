import os
import sys
from pathlib import Path
import dotenv
from openai import OpenAI

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

dotenv.load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("ERROR: No OPENAI_API_KEY")
    sys.exit(1)

client = OpenAI(api_key=api_key)

out_dir = Path("B:/Uwo_Connect/UWO-Connect_F/public/audio/samples")
out_dir.mkdir(parents=True, exist_ok=True)

MODEL = "gpt-4o-mini-tts"

VOICES = [
    {"name": "cedar", "gender": "Male", "desc": "Official Male Tour Voice - Smooth, confident & natural"},
    {"name": "nova", "gender": "Female", "desc": "Official Female Tour Voice - Energetic, warm & engaging"},
    {"name": "alloy", "gender": "Neutral / Female", "desc": "Balanced, versatile & clear"},
    {"name": "echo", "gender": "Male", "desc": "Warm, conversational & friendly"},
    {"name": "onyx", "gender": "Male", "desc": "Deep, authoritative & professional"},
    {"name": "shimmer", "gender": "Female", "desc": "Soft, pleasant & calm"},
    {"name": "fable", "gender": "Male", "desc": "Expressive, storytelling & British tone"},
]

SAMPLE_TEXT_EN = "Hello! Welcome to UWO Connect. I am your AI assistant for customer chat automation, CRM pipelines, and business growth."
SAMPLE_TEXT_HI = "नमस्ते! UWO Connect में आपका स्वागत है। मैं आपका AI असिस्टेंट हूँ जो आपके चैट्स, इनवॉइस और बिज़नेस को ऑटोमेट करता है।"

print(f"Generating samples for {len(VOICES)} voices using model={MODEL}...")

for v in VOICES:
    name = v["name"]
    # 1. English
    en_path = out_dir / f"{name}_en.mp3"
    print(f"Generating {en_path.name}...")
    try:
        res = client.audio.speech.create(model=MODEL, voice=name, input=SAMPLE_TEXT_EN)
        en_path.write_bytes(res.content)
        print(f"  -> Saved {en_path.name} ({len(res.content):,} bytes)")
    except Exception as e:
        print(f"  -> Error for {name} EN: {e}")

    # 2. Hindi
    hi_path = out_dir / f"{name}_hi.mp3"
    print(f"Generating {hi_path.name}...")
    try:
        res = client.audio.speech.create(model=MODEL, voice=name, input=SAMPLE_TEXT_HI)
        hi_path.write_bytes(res.content)
        print(f"  -> Saved {hi_path.name} ({len(res.content):,} bytes)")
    except Exception as e:
        print(f"  -> Error for {name} HI: {e}")

print("All voice samples generated successfully!")
