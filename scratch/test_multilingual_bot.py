"""
Test script to verify Multilingual & Mirror-Language behavior in UWOConnect AI Engine.
Tests prompt construction, language detection, and fallback handling across:
- Romanized Hindi / Hinglish
- Devanagari Hindi
- Punjabi (Gurmukhi)
- Gujarati
- English
"""
import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.services.ai_service import (
    get_language_aware_fallback,
    get_ai_response,
    get_rag_response,
    get_ai_draft
)

def run_multilingual_tests():
    print("=" * 60)
    print("TEST SUITE: MULTILINGUAL & MIRROR-LANGUAGE VALIDATION")
    print("=" * 60)
    
    # 1. Test get_language_aware_fallback across various languages
    test_cases = [
        ("Romanized Hinglish 1", "bhai pricing kya hai?", "Hinglish"),
        ("Romanized Hinglish 2", "kese join karein hume batao", "Hinglish"),
        ("Romanized Hinglish 3", "discount milega kya sirji?", "Hinglish"),
        ("Devanagari Hindi", "नमस्ते, आपके कौन-कौन से प्लान हैं?", "Devanagari"),
        ("Punjabi (Gurmukhi)", "ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ ਜੀ, ਜਾਣਕਾਰੀ ਚਾਹੀਦੀ ਹੈ", "Punjabi"),
        ("Gujarati", "નમસ્તે, તમારા પ્રોડક્ટ્સ વિશે જણાવો", "Gujarati"),
        ("English", "Hello, can you please share your service catalog?", "English")
    ]
    
    biz_name = "AIMALL"
    fallback_passed = 0
    
    print("\n--- 1. Testing Multilingual Fallback Handler ---")
    for label, query, expected_lang in test_cases:
        reply = get_language_aware_fallback(query, biz_name)
        print(f"[{label}]")
        print(f"  Input: {query}")
        print(f"  Reply: {reply}")
        
        # Verify language matching
        if expected_lang == "Hinglish":
            assert "me contact karne ke liye dhanyawad" in reply or "madad" in reply
        elif expected_lang == "Devanagari":
            assert "में संपर्क करने के लिए धन्यवाद" in reply
        elif expected_lang == "Punjabi":
            assert "ਵਿੱਚ ਸੰਪਰਕ ਕਰਨ ਲਈ ਧੰਨਵਾਦ" in reply
        elif expected_lang == "Gujarati":
            assert "માં સંપર્ક કરવા બદલ આભાર" in reply
        elif expected_lang == "English":
            assert "Thank you for contacting" in reply
            
        fallback_passed += 1
        print("  ✓ Match Confirmed\n")
        
    print(f"Fallback Tests Passed: {fallback_passed}/{len(test_cases)}")
    
    # 2. Test get_ai_response & get_rag_response safety when OPENAI_API_KEY is unset/mocked
    print("\n--- 2. Testing AI Function Integrity & Graceful Returns ---")
    
    # Safe fallback if API key is not present in local test
    ai_resp = get_ai_response("bhai price kya hai", "Demo Context")
    print("get_ai_response() output:", ai_resp)
    assert isinstance(ai_resp, str) and len(ai_resp) > 0
    print("  ✓ get_ai_response executed safely without crash")
    
    rag_resp = get_rag_response("kya discount h", [{"text": "Hamare sabhi plans pe 10% discount h", "score": 0.9, "doc_title": "Pricing Doc"}])
    print("get_rag_response() output:", rag_resp)
    assert isinstance(rag_resp, str) and len(rag_resp) > 0
    print("  ✓ get_rag_response executed safely without crash")
    
    draft_resp = get_ai_draft([{"role": "user", "content": "kitna charge lagega"}])
    print("get_ai_draft() output:", draft_resp)
    assert isinstance(draft_resp, str) and len(draft_resp) > 0
    print("  ✓ get_ai_draft executed safely without crash")
    
    print("\n" + "=" * 60)
    print("ALL 10 MULTILINGUAL INTEGRITY CHECKS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_multilingual_tests()
