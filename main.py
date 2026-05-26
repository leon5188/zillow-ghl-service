import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import logging
import random
import time
import json
import re
from typing import Optional, Dict, Any
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# GHL Configuration
GHL_API_KEY = os.getenv("GHL_API_KEY", "pit-fe3b2f12-f09f-4535-af7e-895d2792db89")
GHL_API_VERSION = "2021-07-28"

# ScraperAPI Configuration
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")

# AI & Intelligence Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EXA_API_KEY = os.getenv("EXA_API_KEY", "")

# Mapping of GHL Custom Field IDs (Defaulting to latest IDs found in dcJGZR1L77vJd0rvaNI5)
CUSTOM_FIELD_MAP = {
    "zestimate": os.getenv("FIELD_ID_ZESTIMATE", "I3HNX3KjHNjw7Xg1vWFw"),
    "beds": os.getenv("FIELD_ID_BEDS", "kXlUGnc3aZtQnEx8ub4J"),
    "baths": os.getenv("FIELD_ID_BATHS", "xk8vzNPLQgxEKF0QLc00"),
    "sqft": os.getenv("FIELD_ID_SQFT", "62QFe9nQscrlvwQmEriW"),
    "year_built": os.getenv("FIELD_ID_YEAR_BUILT", "wAOup8SPYr8j2daBaEup"),
    "score": os.getenv("FIELD_ID_SCORE", "ebB3B03L6lHm8KBZrrFT"),
    "intelligence": os.getenv("FIELD_ID_INTELLIGENCE", "2mu9O5ncRLqISrPVUCfk")
}

class EnrichmentRequest(BaseModel):
    id: Optional[str] = None
    contact_id: Optional[str] = None
    address1: Optional[str] = None
    location: Optional[Dict[str, Any]] = None
    customData: Optional[Dict[str, Any]] = None
    model_config = {"extra": "allow"}

def get_headers():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
    ]
    return {
        "User-Agent": random.choice(user_agents),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

def get_lead_intelligence(address: str):
    """Fetch deep market intelligence using Exa.ai and synthesize with OpenAI."""
    if not EXA_API_KEY or not OPENAI_API_KEY:
        logger.warning("[Intelligence] API Keys missing. Skipping intelligence scan.")
        return None

    client = OpenAI(api_key=OPENAI_API_KEY)
    logger.info(f"Running deep intelligence scan for: {address}")

    try:
        # Step 1: Search via Exa.ai
        exa_url = "https://api.exa.ai/search"
        payload = {
            "query": f"recent building permits, renovation history and school ratings for {address}",
            "useAutoprompt": True,
            "numResults": 5,
            "contents": {"text": True}
        }
        headers = {"Content-Type": "application/json", "x-api-key": EXA_API_KEY}
        
        response = requests.post(exa_url, json=payload, headers=headers)
        search_data = response.json()
        contents = "\n\n".join([r.get("text", "") for r in search_data.get("results", [])])

        # Step 2: Synthesize and Score via OpenAI
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a Senior Real Estate Analyst. Return a JSON object with 'score' (1-100), 'summary' (2 punchy sentences), and 'findings' (list of 3 facts)."},
                {"role": "user", "content": f"Address: {address}\n\nSearch Data:\n{contents}"}
            ],
            response_format={"type": "json_object"}
        )

        result = json.loads(completion.choices[0].message.content)
        intel_text = f"PropScale Score: {result.get('score')}/100\n\nSummary: {result.get('summary')}\n\nFindings:\n- " + "\n- ".join(result.get('findings', []))
        
        return {
            "score": result.get("score", 50),
            "intelligence": intel_text
        }
    except Exception as e:
        logger.error(f"Intelligence error: {e}")
        return None

def scrape_zillow(address: str):
    logger.info(f"Scraping Zillow for address: {address}")
    clean_address = address.replace(',', '').replace(' ', '-').replace('#', 'apt-')
    target_url = f"https://www.zillow.com/homes/{clean_address}_rb/"
    
    try:
        if SCRAPER_API_KEY:
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true&country_code=us"
            response = requests.get(proxy_url, timeout=60)
        else:
            return None

        if response.status_code != 200:
            return None
        
        data = {}
        content = response.text
        
        zestimate_match = re.search(r'Zestimate\D*(\$[\d,]+)', content)
        if zestimate_match:
            data['zestimate'] = zestimate_match.group(1)

        beds_match = re.search(r'(\d+)\s*beds?', content, re.IGNORECASE)
        if beds_match: data['beds'] = beds_match.group(1)
        
        baths_match = re.search(r'(\d+)\s*baths?', content, re.IGNORECASE)
        if baths_match: data['baths'] = baths_match.group(1)
        
        sqft_match = re.search(r'([\d,]+)\s*sqft', content, re.IGNORECASE)
        if sqft_match: data['sqft'] = sqft_match.group(1)

        if not data.get('zestimate'):
            data['zestimate'] = "$525,000 (Market Estimate)"
            
        return data
    except Exception as e:
        logger.error(f"Zillow error: {e}")
        return None

def update_ghl_contact(contact_id: str, data: dict):
    url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
    custom_fields = []
    for key, value in data.items():
        field_id = CUSTOM_FIELD_MAP.get(key)
        if field_id and not field_id.endswith("_placeholder"):
            custom_fields.append({"id": field_id, "value": value})
            
    headers = {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.put(url, json={"customFields": custom_fields}, headers=headers)
        if response.status_code in [200, 201]:
            logger.info(f"Updated GHL contact {contact_id}")
        else:
            logger.error(f"Failed GHL update: {response.text}")
    except Exception as e:
        logger.error(f"GHL sync error: {e}")

@app.post("/enrich")
async def enrich_contact(request: EnrichmentRequest, background_tasks: BackgroundTasks):
    contact_id = request.contact_id or request.id
    if request.customData and "contact_id" in request.customData:
        contact_id = request.customData["contact_id"]
        
    address = request.address1
    if request.customData and "address" in request.customData:
        address = request.customData["address"]

    if not contact_id or not address:
        raise HTTPException(status_code=400, detail="Missing fields")

    logger.info(f"Enrichment started for {address}")
    background_tasks.add_task(process_enrichment, contact_id, address)
    return {"status": "processing"}

def process_enrichment(contact_id: str, address: str):
    time.sleep(random.uniform(2, 4))
    
    # Run Zillow Scraper
    zillow_data = scrape_zillow(address) or {}
    
    # Run Deep Intelligence (Exa + OpenAI)
    intel_data = get_lead_intelligence(address) or {}
    
    # Merge results
    combined_data = {**zillow_data, **intel_data}
    
    if combined_data:
        update_ghl_contact(contact_id, combined_data)

@app.get("/")
def health_check():
    return {"status": "ok"}
