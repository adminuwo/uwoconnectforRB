import os
import json
import logging
import requests
import re

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from .ai_service import _get_client

logger = logging.getLogger(__name__)

def fetch_website_meta(url):
    """
    Safely extract title and description snippet from a competitor website.
    Gracefully handles timeouts, SSL errors, or invalid URLs.
    """
    if not url:
        return ""
    
    clean_url = url.strip()
    if not clean_url.startswith(('http://', 'https://')):
        clean_url = 'https://' + clean_url
        
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        }
        res = requests.get(clean_url, headers=headers, timeout=5, verify=False)
        if res.status_code == 200:
            if BeautifulSoup:
                soup = BeautifulSoup(res.text, 'html.parser')
                title = soup.title.string.strip() if soup.title and soup.title.string else ""
                
                meta_desc = ""
                desc_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
                if desc_tag and desc_tag.get('content'):
                    meta_desc = desc_tag['content'].strip()
                    
                # Grab some h1 / h2 text
                headings = [h.get_text().strip() for h in soup.find_all(['h1', 'h2'])[:5] if h.get_text().strip()]
                headings_text = " | ".join(headings)
            else:
                title_m = re.search(r'<title[^>]*>(.*?)</title>', res.text, re.IGNORECASE | re.DOTALL)
                title = title_m.group(1).strip() if title_m else ""
                desc_m = re.search(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']*)["\']', res.text, re.IGNORECASE)
                meta_desc = desc_m.group(1).strip() if desc_m else ""
                headings = re.findall(r'<h[12][^>]*>(.*?)</h[12]>', res.text, re.IGNORECASE)[:5]
                headings_text = " | ".join([re.sub(r'<[^>]+>', '', h).strip() for h in headings if h.strip()])
            
            summary = f"Title: {title}\nDescription: {meta_desc}\nKey Headings: {headings_text}"
            return summary[:1500]
    except Exception as e:
        logger.warning(f"Could not scrape competitor url {url}: {e}")
        return ""
    return ""


def generate_competitor_intelligence(
    client_business_name,
    industry,
    competitor_name,
    competitor_url=None,
    notes=None,
    client_business_description="",
    client_offerings=""
):
    """
    Runs GPT-4o-mini with json_object mode to produce a comprehensive
    competitor intelligence report comparing the competitor directly against
    the client's actual business, offerings, and industry.
    """
    ai_client = _get_client()
    if not ai_client:
        raise ValueError("OpenAI API client is not configured or OPENAI_API_KEY is missing.")

    web_intel = ""
    if competitor_url:
        web_intel = fetch_website_meta(competitor_url)

    c_name = client_business_name or "Your Business"
    c_ind = industry or "General Business / Services"
    c_desc = client_business_description or f"A specialized business operating in {c_ind}."

    system_prompt = (
        "You are an elite competitive intelligence strategist, market research consultant, and business growth advisor.\n\n"
        "CRITICAL INSTRUCTION:\n"
        f"You are performing a custom competitor analysis specifically FOR THE CLIENT'S OWN BUSINESS: '{c_name}' "
        f"operating in the '{c_ind}' industry.\n"
        f"Client Business Overview: {c_desc}\n"
        f"Client Offerings: {client_offerings or 'Custom services and products'}\n\n"
        "DO NOT treat the competitor as a competitor to UwoConnect (the software platform).\n"
        f"Instead, analyze how '{competitor_name}' directly or indirectly competes against '{c_name}' in '{c_ind}'.\n"
        "Highlight competitor strengths, weaknesses, their service and sales gaps, pricing strategies, and provide "
        f"an actionable winning playbook specifically for '{c_name}' to win more market share and close more deals.\n\n"
        "Respond ONLY with a valid JSON object matching the requested schema."
    )

    user_prompt = f"""
CLIENT'S BUSINESS PROFILE:
- Business Name: {c_name}
- Industry / Niche: {c_ind}
- What Client's Business Does: {c_desc}
- Key Offerings: {client_offerings or 'Custom products & services'}

COMPETITOR TO ANALYZE:
- Competitor Name: {competitor_name}
- Competitor Website / Profile: {competitor_url or 'N/A'}
- Specific Notes / Observations: {notes or 'None provided'}
{f'- Scraped Website Context: {web_intel}' if web_intel else ''}

TASK:
Analyze '{competitor_name}' head-to-head against '{c_name}'.
Evaluate their market positioning, offerings, customer friction points, and provide actionable strategy for '{c_name}' to beat them.

Return a JSON object with this exact structure:
{{
  "client_context_summary": "1-2 sentence overview of {c_name}'s market position vs {competitor_name}",
  "competitor_summary": {{
    "tagline": "Short brand essence or positioning of {competitor_name}",
    "core_offering": "What {competitor_name} primarily sells or provides in this industry",
    "estimated_scale": "Local / Regional / National / Global",
    "target_audience": "Who they primarily target",
    "business_model": "Their primary revenue or distribution model"
  }},
  "advantage_score": 80,
  "advantage_headline": "Compelling headline explaining {c_name}'s core competitive edge over {competitor_name}",
  "advantage_summary": "Paragraph explaining why and how {c_name} beats {competitor_name} in speed, customer experience, flexibility, or value in this market",
  "automation_audit": {{
    "whatsapp_presence": "e.g. Basic personal WhatsApp / Manual business app / Absent / Automated",
    "whatsapp_takeaway": "Actionable takeaway on how {c_name} can win on direct customer communication",
    "lead_response_speed": "e.g. Slow (4-12 hours) / Moderate (1-2 hours) / Fast",
    "speed_takeaway": "How {c_name}'s fast response captures ready buyers before {competitor_name}",
    "booking_friction": "High / Medium / Low",
    "friction_takeaway": "How {c_name} eliminates ordering/consultation friction",
    "self_serve_catalog": "e.g. Static PDF / None / Online store",
    "after_hours_coverage": "e.g. Zero coverage (misses evening/weekend inquiries)",
    "coverage_takeaway": "How 24/7 capture lets {c_name} capture leads while {competitor_name} is closed",
    "critical_gaps": [
      "Competitor gap 1 in serving customers in this industry...",
      "Competitor gap 2...",
      "Competitor gap 3..."
    ]
  }},
  "swot": {{
    "strengths": ["Competitor strength 1", "Competitor strength 2", "Competitor strength 3"],
    "weaknesses": ["Competitor weakness 1", "Competitor weakness 2", "Competitor weakness 3"],
    "opportunities": ["Opportunity 1 for {c_name}", "Opportunity 2 for {c_name}", "Opportunity 3 for {c_name}"],
    "threats": ["Threat 1 from {competitor_name}", "Threat 2 from {competitor_name}"]
  }},
  "pricing_offers": {{
    "positioning": "Budget / Mid-market / Premium / Enterprise",
    "key_offers": ["Competitor package 1", "Competitor package 2"],
    "pricing_model": "e.g. Fixed per project / Subscription / Custom quote / Per-transaction",
    "gap_to_exploit": "Specific strategic pricing or packaging gap where {c_name} can offer superior value or bundled perks to win clients"
  }},
  "channel_scores": {{
    "whatsapp_speed": 35,
    "omnichannel_sync": 40,
    "self_serve_convenience": 30,
    "followup_persistence": 45
  }},
  "winning_playbook": {{
    "title": "Strategy for {c_name} to Win Against {competitor_name}",
    "recommended_flow": "Step-by-step customer journey flow {c_name} should use to convert prospects considering {competitor_name}",
    "broadcast_angle": "High-converting marketing or broadcast campaign angle to attract customers from {competitor_name}",
    "quick_wins": [
      "Tactical quick win 1 for {c_name}",
      "Tactical quick win 2 for {c_name}",
      "Tactical quick win 3 for {c_name}"
    ],
    "hook_script": "Ready-to-use high-converting message pitch or ad headline {c_name} can use directly"
  }}
}}
"""

    response = ai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=2500
    )

    content = response.choices[0].message.content
    data = json.loads(content)
    # Ensure backward compatibility with any components expecting uwoconnect_playbook
    if 'winning_playbook' in data and 'uwoconnect_playbook' not in data:
        data['uwoconnect_playbook'] = data['winning_playbook']
    elif 'uwoconnect_playbook' in data and 'winning_playbook' not in data:
        data['winning_playbook'] = data['uwoconnect_playbook']
    return data


def discover_industry_competitors(
    client_business_name,
    industry,
    client_business_description="",
    location="India",
    already_tracked_names=None
):
    """
    Identifies 3-5 real or archetype direct competitors operating in the same industry/niche
    as the client, giving the client instant 1-click intelligence suggestions.
    """
    ai_client = _get_client()
    if not ai_client:
        return []

    c_name = client_business_name or "Your Business"
    c_ind = industry or "General Services"
    c_desc = client_business_description or f"A business offering products and services in {c_ind}."
    loc = location or "India"
    excluded = ", ".join(already_tracked_names or [])

    system_prompt = (
        "You are an expert market intelligence advisor and competitive analyst.\n"
        "Your goal is to detect 4 direct or prominent competitors/rivals for a specific business.\n"
        "Identify real, well-known, or typical high-traction competitors in their industry and region.\n"
        "Respond ONLY with a valid JSON object matching the requested schema."
    )

    user_prompt = f"""
CLIENT BUSINESS:
- Name: {c_name}
- Industry / Niche: {c_ind}
- What They Do: {c_desc}
- Region / Market: {loc}
{f"- Do NOT suggest these already tracked names: {excluded}" if excluded else ""}

TASK:
Identify 4 top direct or close competitor businesses operating in this space that {c_name} should benchmark against.
For each competitor, provide:
1. competitor_name: The company/brand name
2. competitor_website: Official website or clean domain (e.g. "https://example.com" or "example.com")
3. category: Sub-niche or positioning (e.g. "Enterprise Leader", "Fast-Growing Challenger", "D2C Specialist")
4. why_rival: 1 crisp sentence explaining why {c_name} competes with them or should watch them
5. threat_level: "High" | "Medium"
6. suggested_angle: 1 sentence on the strategic angle {c_name} can exploit against them

Return JSON with this exact structure:
{{
  "suggestions": [
    {{
      "competitor_name": "Name",
      "competitor_website": "https://...",
      "category": "...",
      "why_rival": "...",
      "threat_level": "High",
      "suggested_angle": "..."
    }}
  ]
}}
"""

    try:
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=1000
        )
        data = json.loads(response.choices[0].message.content)
        return data.get('suggestions', [])
    except Exception as e:
        logger.error(f"Failed to discover competitors: {e}")
        return []

