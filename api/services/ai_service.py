import os
import re
import numpy as np
from openai import OpenAI

_openai_client = None

def _get_client():
    """Lazy-initialize the OpenAI client so missing API key doesn't crash at import time."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client

# Keep backward compat — functions that used `client` directly now call _get_client()
client = None  # Will be resolved lazily via _get_client()

# ===== EMBEDDING FUNCTIONS =====

EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dimensions, cheap & fast

def get_embedding(text):
    """
    OpenAI se text ka embedding vector nikalta hai (1536 dimensions).
    Cost: ~$0.02 per 1 million tokens — bahut sasta hai.
    """
    try:
        # Clean and limit text
        text = text.replace("\n", " ").strip()
        if not text:
            return []
        ai_client = _get_client()
        if not ai_client:
            return []
        response = ai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"Embedding Error: {str(e)}")
        return []


def chunk_text(text, chunk_size=800, overlap=100):
    """
    Text ko overlapping chunks mein todta hai for better retrieval.
    
    chunk_size: words per chunk (800 words ~ 1000 tokens)
    overlap: overlap words between chunks for context continuity
    """
    words = text.split()
    chunks = []
    
    if len(words) <= chunk_size:
        # Small document — single chunk
        return [text.strip()]
    
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk.strip())
        start = end - overlap  # Overlap for context continuity
    
    return [c for c in chunks if c.strip()]


def cosine_similarity(vec1, vec2):
    """
    Cosine similarity between two vectors.
    Returns: -1 (opposite) to 1 (identical)
    """
    vec1 = np.array(vec1)
    vec2 = np.array(vec2)
    
    dot = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return float(dot / (norm1 * norm2))


def find_relevant_chunks(query_embedding, chunks_with_embeddings, top_k=5, query_text=None):
    """
    Query embedding and optional query_text ke closest chunks dhundta hai.
    Supports hybrid scoring (dense cosine similarity + keyword matching)
    and preserves source_url, page_title, and heading_path.
    Returns: top_k most relevant chunks sorted by similarity.
    """
    query_tokens = [w.lower() for w in re.findall(r'\w+', (query_text or '').strip()) if len(w) > 1] if query_text else []
    query_phrase = (query_text or '').strip().lower()

    scored = []
    for chunk in chunks_with_embeddings:
        dense_score = 0.0
        emb = chunk.get('embedding')
        if query_embedding and emb and len(emb) == 1536:
            dense_score = cosine_similarity(query_embedding, emb)

        # Lexical score if query_text is available
        lexical_score = 0.0
        if query_tokens:
            text_lower = (chunk.get('text') or '').lower()
            title_lower = (chunk.get('doc_title') or '').lower()
            heading_lower = (chunk.get('heading_path') or '').lower()

            if query_phrase and query_phrase in text_lower:
                lexical_score += 0.3
            if query_phrase and (query_phrase in title_lower or query_phrase in heading_lower):
                lexical_score += 0.4

            for token in query_tokens:
                if token in text_lower:
                    lexical_score += 0.1
                if token in title_lower or token in heading_lower:
                    lexical_score += 0.2

        # Combined hybrid score (capped at 1.0)
        final_score = (dense_score * 0.7) + min(lexical_score, 0.3) if query_tokens else dense_score

        scored.append({
            'text': chunk.get('text') or chunk.get('chunk_text', ''),
            'score': round(final_score, 4),
            'dense_score': round(dense_score, 4),
            'doc_title': chunk.get('doc_title') or chunk.get('page_title', ''),
            'source_url': chunk.get('source_url', ''),
            'heading_path': chunk.get('heading_path', ''),
        })
    
    # Sort by similarity score (highest first)
    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:top_k]


# ===== AI RESPONSE FUNCTIONS =====

def get_ai_response(prompt, context="", client_model=None):
    """
    Generates a response using OpenAI based on the provided prompt and context.
    Supports tool calling for Google Calendar if client_model is provided.
    """
    import json
    try:
        ai_client = _get_client()
        if not ai_client:
            return "AI service is not configured. Please add an OPENAI_API_KEY."
        biz_name = getattr(client_model, 'business_name', None) or 'our business'
        system_prompt = f"""You are a professional, polite, and helpful AI customer assistant for {biz_name}.
Business Context & Guidelines:
{context}

CRITICAL MULTILINGUAL & MIRROR-LANGUAGE RULES:
1. STRICT LANGUAGE MATCHING: You MUST detect the exact language, dialect, and script used by the customer in their message, and reply in the EXACT SAME LANGUAGE and tone:
   - If the customer writes in Romanized Hindi / Hinglish (e.g. 'price kya hai', 'order kaise karein', 'discount milega kya', 'kya features hain'), you MUST reply in natural, polite Romanized Hindi / Hinglish.
   - If the customer writes in Devanagari Hindi (e.g. 'नमस्ते, मुझे उत्पाद की जानकारी चाहिए'), reply in pure Devanagari Hindi.
   - If the customer writes in regional Indian languages (Punjabi, Gujarati, Marathi, Bengali, Tamil, Telugu, Kannada, Malayalam, etc.), reply in that exact language.
   - If the customer writes in English, reply in English.
   - If the customer writes in any international language (Spanish, Arabic, French, German, etc.), reply in that language.
   - NEVER reply in English if the customer messaged in Hindi, Hinglish, or any regional language!
2. Be polite, concise, and helpful. Keep responses natural and well-suited for WhatsApp and chat messaging.
3. Only book appointments if the user explicitly confirms the date and time."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "check_calendar_availability",
                    "description": "Check if there are free time slots in the business Google Calendar for a specific date.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "The date to check in YYYY-MM-DD format (e.g., '2023-10-15')."
                            }
                        },
                        "required": ["date"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "book_appointment",
                    "description": "Book an appointment on the business Google Calendar.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "The date of the appointment in YYYY-MM-DD format."
                            },
                            "time": {
                                "type": "string",
                                "description": "The time of the appointment in 24-hour format HH:MM (e.g., '14:30' for 2:30 PM)."
                            },
                            "customer_name": {
                                "type": "string",
                                "description": "The name of the customer booking the appointment."
                            }
                        },
                        "required": ["date", "time", "customer_name"]
                    }
                }
            }
        ]

        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=500
        )
        
        response_message = response.choices[0].message
        
        # Check if the model decided to call any tools
        if response_message.tool_calls and client_model and client_model.google_calendar_enabled:
            from .google_calendar_service import GoogleCalendarService
            messages.append(response_message)  # Extend conversation with assistant's tool call
            
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                tool_result = ""
                if function_name == "check_calendar_availability":
                    target_date = function_args.get("date")
                    tool_result = GoogleCalendarService.check_availability(client_model, target_date)
                elif function_name == "book_appointment":
                    target_date = function_args.get("date")
                    target_time = function_args.get("time")
                    customer_name = function_args.get("customer_name")
                    tool_result = GoogleCalendarService.book_appointment(client_model, target_date, target_time, customer_name)
                    
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": tool_result,
                })
                
            # Send the tool results back to the model to get the final textual response
            second_response = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=500
            )
            return second_response.choices[0].message.content
            
        return response_message.content
        
    except Exception as e:
        print(f"AI Error: {str(e)}") 
        return "I'm sorry, I'm having trouble thinking right now. Please try again later."


def get_rag_response(query, relevant_chunks, client_model=None):
    """
    RAG Response — AI sirf retrieved chunks ke basis pe jawab deta hai.
    
    relevant_chunks: list of dicts with 'text', 'score', 'doc_title'
    Supports tool calling for Google Calendar if client_model is provided.
    """
    import json
    try:
        ai_client = _get_client()
        if not ai_client:
            return "AI service is not configured. Please add an OPENAI_API_KEY."
        # Build context from relevant chunks
        context_parts = []
        for i, chunk in enumerate(relevant_chunks, 1):
            source = f" (from: {chunk['doc_title']})" if chunk.get('doc_title') else ""
            url_str = f" [URL: {chunk['source_url']}]" if chunk.get('source_url') else ""
            heading_str = f" [Section: {chunk['heading_path']}]" if chunk.get('heading_path') else ""
            context_parts.append(f"[Document Section {i}{source}{heading_str}{url_str}]\n{chunk['text']}")
        
        knowledge_context = "\n\n".join(context_parts)
        biz_name = getattr(client_model, 'business_name', None) or 'our business'
        system_prompt = f"""You are a professional, polite, and helpful AI customer assistant for {biz_name}. You answer customer questions based on the business documents provided below.

CRITICAL MULTILINGUAL & MIRROR-LANGUAGE RULES:
1. STRICT LANGUAGE MATCHING: You MUST detect the exact language, dialect, and script used by the customer in their query, and reply in the EXACT SAME LANGUAGE and tone:
   - If the customer writes in Romanized Hindi / Hinglish (e.g. 'price kya hai', 'order kaise karein', 'kya discount milega', 'features kya hain'), you MUST reply in natural, polite Romanized Hindi / Hinglish.
   - If the customer writes in Devanagari Hindi (e.g. 'नमस्ते, मुझे उत्पाद की जानकारी चाहिए'), reply in pure Devanagari Hindi.
   - If the customer writes in regional Indian languages (Punjabi, Gujarati, Marathi, Bengali, Tamil, Telugu, Kannada, Malayalam, etc.), reply in that exact language.
   - If the customer writes in English, reply in English.
   - If the customer writes in any international language (Spanish, Arabic, French, etc.), reply in that language.
   - NEVER reply in English if the customer messaged in Hindi, Hinglish, or any regional language!

STRICT CONTENT & CITATION RULES:
1. Use the provided business document sections to answer factual questions about products, pricing, policies, and services.
2. If an answer is sourced from a website section that has a URL, cite the page title and URL so the user can verify or view details (e.g. 'More details: https://...').
3. Do NOT invent facts or hallucinate outside information for business-specific questions.
4. If the user is greeting (e.g. 'Hi', 'Hello', 'Namaste', 'Kem cho', 'Sat Sri Akal') or thanking you, reply warmly in their language.
5. If a factual question's answer is NOT found in the documents, apologize politely in the CUSTOMER'S SAME LANGUAGE (for Hinglish: 'Maaf kijiye, hamare paas iski jaankari knowledge base me nahi hai. Kripya humse directly contact karein.', for Hindi: 'क्षमा करें, हमारे पास अभी इसकी जानकारी उपलब्ध नहीं है। कृपया हमसे सीधे संपर्क करें।', for English: 'I\\'m sorry, I don\\'t have information about that in our knowledge base. Please contact us directly for help.')
6. Be concise, friendly, and natural for chat/WhatsApp messaging.

--- RELEVANT BUSINESS KNOWLEDGE ---
{knowledge_context}
--- END OF KNOWLEDGE ---"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "check_calendar_availability",
                    "description": "Check if there are free time slots in the business Google Calendar for a specific date.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "The date to check in YYYY-MM-DD format."
                            }
                        },
                        "required": ["date"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "book_appointment",
                    "description": "Book an appointment on the business Google Calendar.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "The date of the appointment in YYYY-MM-DD format."
                            },
                            "time": {
                                "type": "string",
                                "description": "The time of the appointment in 24-hour format HH:MM."
                            },
                            "customer_name": {
                                "type": "string",
                                "description": "The name of the customer booking the appointment."
                            }
                        },
                        "required": ["date", "time", "customer_name"]
                    }
                }
            }
        ]

        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=600,
            temperature=0.3
        )
        
        response_message = response.choices[0].message
        
        # Check if the model decided to call any tools
        if response_message.tool_calls and client_model and client_model.google_calendar_enabled:
            from .google_calendar_service import GoogleCalendarService
            messages.append(response_message)
            
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                tool_result = ""
                if function_name == "check_calendar_availability":
                    target_date = function_args.get("date")
                    tool_result = GoogleCalendarService.check_availability(client_model, target_date)
                elif function_name == "book_appointment":
                    target_date = function_args.get("date")
                    target_time = function_args.get("time")
                    customer_name = function_args.get("customer_name")
                    tool_result = GoogleCalendarService.book_appointment(client_model, target_date, target_time, customer_name)
                    
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": tool_result,
                })
                
            second_response = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=600
            )
            return second_response.choices[0].message.content

        return response_message.content
    except Exception as e:
        print(f"RAG AI Error: {str(e)}")
        return "I'm sorry, I'm unable to process your request right now. Please try again later."


def get_platform_assistance(user_query):
    """
    Specific assistant for explaining the Aisaconnect platform.
    """
    platform_context = """
    Aisaconnect (Kon Hai Best) is a WhatsApp Automation SaaS. 
    Features:
    1. Automated Keyword Replies: Set specific responses for keywords.
    2. Global Greeting Message: Auto-welcome new customers.
    3. Visual Workflow Builder: Create complex multi-step automations.
    4. Team Inbox: Real-time chat dashboard for multiple agents.
    5. Broadcast Manager: Send bulk marketing messages.
    clients use it to automate their business communication on WhatsApp.
    """
    return get_ai_response(user_query, platform_context)


def get_ai_draft(chat_history):
    """
    Generates a suggested reply based on the chat history.
    chat_history: list of dicts [{'role': 'user'/'assistant', 'content': 'message'}]
    """
    try:
        ai_client = _get_client()
        if not ai_client:
            return "AI service is not configured."
        system_prompt = (
            "You are a professional customer support agent. Generate a concise, friendly, and helpful draft reply "
            "to the user's last message, taking into account the context of the conversation.\n"
            "CRITICAL LANGUAGE RULE: You MUST reply in the EXACT SAME language, dialect, and script as the customer's last message "
            "(e.g., Romanized Hindi/Hinglish, Devanagari Hindi, Punjabi, Gujarati, Bengali, Marathi, English, etc.). "
            "Never reply in English if the customer wrote in Hindi, Hinglish, or any regional language. Output ONLY the draft message."
        )
        
        # Prepare messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(chat_history)
        
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=300,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Draft Error: {str(e)}")
        return "I'm sorry, I couldn't generate a draft right now."


def get_language_aware_fallback(text, business_name="our business"):
    """
    Returns a polite fallback greeting in the user's detected language/script
    if AI is unavailable or produces an empty response.
    """
    import re
    if not text:
        return f"Thank you for contacting {business_name}. How can we assist you today?"
        
    # Check for Devanagari script (Hindi, Marathi, Nepali)
    if any('\u0900' <= char <= '\u097F' for char in text):
        return f"{business_name} में संपर्क करने के लिए धन्यवाद! आज हम आपकी क्या सहायता कर सकते हैं?"
        
    # Check for Gurmukhi script (Punjabi)
    if any('\u0A00' <= char <= '\u0A7F' for char in text):
        return f"{business_name} ਵਿੱਚ ਸੰਪਰਕ ਕਰਨ ਲਈ ਧੰਨਵਾਦ! ਅਸੀਂ ਅੱਜ ਤੁਹਾਡੀ ਕੀ ਮਦਦ ਕਰ ਸਕਦੇ ਹਾਂ?"
        
    # Check for Gujarati script
    if any('\u0A80' <= char <= '\u0AFF' for char in text):
        return f"{business_name} માં સંપર્ક કરવા બદલ આભાર! અમે તમને કેવી રીતે મદદ કરી શકીએ?"

    # Check for common Romanized Hindi / Hinglish keywords
    text_lower = text.lower()
    hinglish_markers = [
        'kya', 'hai', 'hain', 'kaise', 'karein', 'krna', 'karna', 'bhai', 'batao',
        'chahiye', 'chahie', 'chhaiye', 'kitna', 'kitne', 'milega', 'hume', 'humara',
        'aap', 'aapka', 'shukriya', 'dhanyawad', 'namaste', 'namaskar', 'sirji', 'bolo'
    ]
    if any(re.search(r'\b' + re.escape(w) + r'\b', text_lower) for w in hinglish_markers):
        return f"{business_name} me contact karne ke liye dhanyawad! Hum aaj aapki kya madad kar sakte hain?"
        
    return f"Thank you for contacting {business_name}. How can we assist you with our products or services today?"

