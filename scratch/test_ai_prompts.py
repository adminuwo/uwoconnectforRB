"""
Extended prompt construction and payload test for OpenAI GPT-4o-mini
"""
import os
import sys
import django
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.services import ai_service

def test_ai_prompt_construction():
    print("=" * 60)
    print("TEST: AI PROMPT MIRROR-LANGUAGE SYSTEM VERIFICATION")
    print("=" * 60)
    
    mock_client = MagicMock()
    mock_completion = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "Haanji, hamara plan ₹999 se start hota hai!"
    mock_message.tool_calls = None
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_completion.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_completion
    
    # 1. Test get_ai_response with Mock Client
    with patch.object(ai_service, '_get_client', return_value=mock_client):
        response = ai_service.get_ai_response(
            prompt="bhai price kitna hai",
            context="Business sells SaaS subscriptions",
            client_model=MagicMock(business_name="TestBiz", google_calendar_enabled=False)
        )
        
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs['messages']
        system_msg = next(m['content'] for m in messages if m['role'] == 'system')
        user_msg = next(m['content'] for m in messages if m['role'] == 'user')
        
        print("\n[get_ai_response Verification]")
        print("User Query:", user_msg)
        print("Bot Mock Reply:", response)
        
        assert "CRITICAL MULTILINGUAL & MIRROR-LANGUAGE RULES" in system_msg
        assert "Romanized Hindi / Hinglish" in system_msg
        assert "Devanagari Hindi" in system_msg
        assert "regional Indian languages" in system_msg
        assert "NEVER reply in English if the customer messaged in Hindi" in system_msg
        print("  ✓ Strict Mirror-Language system rules present in get_ai_response prompt payload!")

    # 2. Test get_rag_response with Mock Client
    with patch.object(ai_service, '_get_client', return_value=mock_client):
        chunks = [
            {"text": "Standard plan costs Rs 499", "score": 0.85, "doc_title": "Pricing Doc"}
        ]
        rag_response = ai_service.get_rag_response(
            query="kya discount milega?",
            relevant_chunks=chunks,
            client_model=MagicMock(business_name="TestBiz", google_calendar_enabled=False)
        )
        
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs['messages']
        system_msg = next(m['content'] for m in messages if m['role'] == 'system')
        
        print("\n[get_rag_response Verification]")
        print("RAG Query: kya discount milega?")
        print("RAG Mock Reply:", rag_response)
        
        assert "CRITICAL MULTILINGUAL & MIRROR-LANGUAGE RULES" in system_msg
        assert "STRICT LANGUAGE MATCHING" in system_msg
        assert "NEVER reply in English" in system_msg
        assert "Maaf kijiye" in system_msg
        print("  ✓ Strict Mirror-Language system rules present in get_rag_response prompt payload!")

    # 3. Test get_ai_draft with Mock Client
    with patch.object(ai_service, '_get_client', return_value=mock_client):
        draft_response = ai_service.get_ai_draft(
            chat_history=[{"role": "user", "content": "kitne paise lagenge"}]
        )
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs['messages']
        system_msg = next(m['content'] for m in messages if m['role'] == 'system')
        
        print("\n[get_ai_draft Verification]")
        print("Draft Mock Reply:", draft_response)
        assert "CRITICAL LANGUAGE RULE" in system_msg
        assert "Romanized Hindi/Hinglish" in system_msg
        print("  ✓ Strict Mirror-Language rules present in get_ai_draft prompt payload!")

    print("\n" + "=" * 60)
    print("ALL PROMPT PAYLOAD CHECKS CONFIRMED 100% OPERATIONAL!")
    print("=" * 60)

if __name__ == "__main__":
    test_ai_prompt_construction()
