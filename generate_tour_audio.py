import os
import sys
import time
from pathlib import Path
import dotenv
from openai import OpenAI

# Force UTF-8 encoding on Windows console
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Load backend .env
dotenv.load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("ERROR: OPENAI_API_KEY not found in environment!")
    sys.exit(1)

client = OpenAI(api_key=api_key)

# Base output directory in Frontend public
base_out_dir = Path("B:/Uwo_Connect/UWO-Connect_F/public/audio/tour")
base_out_dir.mkdir(parents=True, exist_ok=True)

STEPS = [
    {
        "key": "welcome",
        "en": "Welcome to UWO Connect! Your all-in-one business growth command center. Take a quick one-minute tour of your essential tools.",
        "hi": "UWO Connect में आपका स्वागत है! यह आपका ऑल-इन-वन बिज़नेस ऑटोमेशन कमांड सेंटर है। आइए, एक मिनट में इसके ज़रूरी टूल्स को समझते हैं।"
    },
    {
        "key": "channels",
        "en": "Channels. Connect your WhatsApp Cloud API, Instagram, and Facebook in one click. All customer messages arrive in one unified hub.",
        "hi": "चैनल्स। अपने वॉट्सऐप क्लाउड एपीआई, इंस्टाग्राम और फेसबुक को एक क्लिक में कनेक्ट करें। आपके सारे कस्टमर मेसेज एक ही जगह आएंगे।"
    },
    {
        "key": "automations",
        "en": "24/7 AI Auto Replies. Smart AI bot that instantly answers common customer questions about prices, timings, and FAQs round the clock.",
        "hi": "24/7 एआई ऑटो रिप्लाई। स्मार्ट एआई बॉट आपके कस्टमर्स के प्राइस, टाइमिंग और सवालों का तुरंत 24 घंटे जवाब देता है।"
    },
    {
        "key": "workflows",
        "en": "Chat Workflows. Build interactive chat flows to automatically collect customer details, book appointments, and follow up effortlessly.",
        "hi": "चैट वर्कफ्लोज़। इंटरैक्टिव चैट फ्लो बनाएं जो कस्टमर की डिटेल्स खुद कलेक्ट करे, अपॉइंटमेंट्स बुक करे और फॉलो-अप ले।"
    },
    {
        "key": "crm",
        "en": "Leads and CRM. All captured customer contacts, phone numbers, and full chat histories are automatically organized in your database.",
        "hi": "लीड्स और सीआरएम। आपके सारे कस्टमर कॉन्टैक्ट्स, फोन नंबर्स और चैट हिस्ट्री यहाँ ऑटोमैटिकली सेव और ऑर्गनाइज़ होते हैं।"
    },
    {
        "key": "inbox",
        "en": "Team Inbox. View and reply to customer chats across WhatsApp and Instagram in a single unified inbox where your team can live chat anytime.",
        "hi": "टीम इनबॉक्स। वॉट्सऐप और इंस्टाग्राम के सभी कस्टमर मेसेजेस को एक ही शेयर्ड इनबॉक्स में देखें और अपनी टीम के साथ लाइव चैट करें।"
    },
    {
        "key": "knowledge",
        "en": "AI Knowledge Base. Upload your company documents, PDFs, and brochures. Your smart AI bot learns your business information to answer customer queries with 100% precision 24/7.",
        "hi": "एआई नॉलेज बेस। अपनी कंपनी के पीडीएफ, ब्रोशर और फाइल्स यहाँ अपलोड करें। आपका स्मार्ट एआई बॉट आपके बिज़नेस को सीखकर कस्टमर्स को 24 घंटे सटीक जवाब देगा।"
    },
    {
        "key": "campaigns",
        "en": "WhatsApp Broadcasts. Send festival offers, discounts, and announcement messages to all your contacts in one click with high open rates.",
        "hi": "वॉट्सऐप ब्रॉडकास्ट। अपने सभी कस्टमर्स को फेस्टिव ऑफर्स, डिस्काउंट्स और नए ऑफर्स एक क्लिक में सीधे वॉट्सऐप पर भेजें।"
    },
    {
        "key": "catalog",
        "en": "E-Commerce Catalog. Add your products and share instant checkout links to sell directly inside customer WhatsApp chats.",
        "hi": "ई-कॉमर्स कैटलॉग। अपने प्रोडक्ट्स ऐड करें और डायरेक्ट चेकआउट लिंक शेयर करके वॉट्सऐप चैट के अंदर ही ऑनलाइन सेल करें।"
    },
    {
        "key": "invoices",
        "en": "GST Tax Invoices. Create professional branded tax invoices and send direct payment links to customers on WhatsApp with instant PDF downloads.",
        "hi": "जीएसटी टैक्स इनवॉइस। ब्रांडेड टैक्स इनवॉइस बनाएं और वॉट्सऐप पर डायरेक्ट पेमेंट लिंक और पीडीएफ बिल भेजें।"
    },
    {
        "key": "payments",
        "en": "Razorpay Payments. Connect your Razorpay account so customer payments via UPI or Card go straight to your bank account with zero middlemen.",
        "hi": "रेज़रपे पेमेंट्स। अपना रेज़रपे अकाउंट कनेक्ट करें ताकि कस्टमर के यूपीआई और कार्ड पेमेंट्स सीधे आपके बैंक अकाउंट में आएं।"
    }
]

MODEL = "gpt-4o-mini-tts"
VOICES = [
    {"gender": "Female", "name": "nova", "folder": "nova"},
    {"gender": "Male", "name": "cedar", "folder": "cedar"},
]

print("=" * 70)
print(f"🎙️ UWO Connect Tour Audio Generator using OpenAI [{MODEL}]")
print(f"👥 Voices: Nova (Female) & Cedar (Male)")
print(f"🌐 Languages: English (en) & Hindi (hi) | Steps: {len(STEPS)}")
print("=" * 70)

total_generated = 0
start_time = time.time()

for voice_info in VOICES:
    voice_name = voice_info["name"]
    gender = voice_info["gender"]
    folder_name = voice_info["folder"]

    voice_dir = base_out_dir / folder_name
    voice_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n📢 Processing Voice: {voice_name.upper()} ({gender}) -> Folder: {voice_dir}")
    print("-" * 50)

    for i, step in enumerate(STEPS, 1):
        key = step["key"]

        # 1. English Audio
        en_target = voice_dir / f"{key}_en.mp3"
        print(f"  [{i}/{len(STEPS)}] Generating English: {en_target.name}...")
        try:
            resp_en = client.audio.speech.create(
                model=MODEL,
                voice=voice_name,
                input=step["en"]
            )
            en_target.write_bytes(resp_en.content)
            print(f"      ✅ Saved {en_target.name} ({len(resp_en.content):,} bytes)")
            total_generated += 1

            # If nova (default female voice), also copy/save to root tour/ folder for compatibility
            if voice_name == "nova":
                root_en = base_out_dir / f"{key}_en.mp3"
                root_en.write_bytes(resp_en.content)

        except Exception as e:
            print(f"      ❌ ERROR generating EN for {key} ({voice_name}): {e}")

        # 2. Hindi Audio
        hi_target = voice_dir / f"{key}_hi.mp3"
        print(f"  [{i}/{len(STEPS)}] Generating Hindi:   {hi_target.name}...")
        try:
            resp_hi = client.audio.speech.create(
                model=MODEL,
                voice=voice_name,
                input=step["hi"]
            )
            hi_target.write_bytes(resp_hi.content)
            print(f"      ✅ Saved {hi_target.name} ({len(resp_hi.content):,} bytes)")
            total_generated += 1

            # If nova (default female voice), also copy/save to root tour/ folder for compatibility
            if voice_name == "nova":
                root_hi = base_out_dir / f"{key}_hi.mp3"
                root_hi.write_bytes(resp_hi.content)

        except Exception as e:
            print(f"      ❌ ERROR generating HI for {key} ({voice_name}): {e}")

        time.sleep(0.2)

elapsed = round(time.time() - start_time, 1)
print("\n" + "=" * 70)
print(f"🎉 Complete! Successfully generated {total_generated} MP3 audio files in {elapsed}s.")
print(f"📁 Audio files saved to: {base_out_dir}")
print("=" * 70)
