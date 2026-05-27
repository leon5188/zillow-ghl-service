import requests
from bs4 import BeautifulSoup
import csv
import time
import os
import json
from dotenv import load_dotenv

# Load API keys from the .env file in the parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")

if not SCRAPER_API_KEY:
    print("❌ Error: SCRAPER_API_KEY is not set. Please add it to your .env file.")
    exit(1)

def search_active_agents(city_zip: str, pages: int = 1):
    """
    Uses ScraperAPI to find active real estate agents on Zillow's directory
    for a specific city or zip code.
    """
    agents_collected = []
    
    print(f"🚀 Starting Agent Extraction for: {city_zip}")
    print("This might take a few minutes as we are bypassing anti-bot systems...\n")

    for page in range(1, pages + 1):
        # Zillow Agent Directory URL format
        target_url = f"https://www.zillow.com/professionals/real-estate-agent-reviews/{city_zip.replace(' ', '-')}/?page={page}"
        
        # ScraperAPI Proxy URL (Using JS render to load phone numbers if hidden)
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true"
        
        print(f"📄 Scraping Page {page}...")
        
        try:
            response = requests.get(proxy_url, timeout=60)
            
            if response.status_code != 200:
                print(f"⚠️ Failed to retrieve page {page}. Status: {response.status_code}")
                continue

            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all agent profile cards on the page
            # Note: Zillow CSS classes change frequently. We use a broad search for article tags or specific data attributes.
            agent_cards = soup.find_all('article')
            
            for card in agent_cards:
                agent_data = {
                    "first_name": "",
                    "last_name": "",
                    "company_name": "",
                    "phone": "",
                    "city": city_zip,
                    "profile_url": ""
                }
                
                # Extract Name
                name_tag = card.find('h3')
                if name_tag:
                    full_name = name_tag.get_text(strip=True).split(',') # e.g. "Sarah Johnson, Realtor"
                    name_parts = full_name[0].split(' ')
                    agent_data["first_name"] = name_parts[0]
                    agent_data["last_name"] = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

                # Extract Brokerage/Company
                # Usually follows the name or has specific classes. We look for 'Real Estate' or similar text nearby.
                company_tags = card.find_all('span')
                for tag in company_tags:
                    text = tag.get_text(strip=True)
                    if "Realty" in text or "Keller" in text or "Group" in text or "Real Estate" in text:
                        agent_data["company_name"] = text
                        break

                # Extract Phone (Often formatted like (555) 123-4567)
                import re
                phone_match = re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', card.get_text())
                if phone_match:
                    agent_data["phone"] = phone_match.group()

                # Extract Profile Link
                link_tag = card.find('a', href=True)
                if link_tag and '/profile/' in link_tag['href']:
                    agent_data["profile_url"] = f"https://www.zillow.com{link_tag['href']}"

                # Only save if we got at least a name and a phone number
                if agent_data["first_name"] and agent_data["phone"]:
                    agents_collected.append(agent_data)
                    print(f"✅ Found: {agent_data['first_name']} {agent_data['last_name']} | {agent_data['company_name']} | {agent_data['phone']}")

        except Exception as e:
            print(f"❌ Error on page {page}: {e}")
            
        # Polite delay
        time.sleep(2)

    return agents_collected

def export_to_ghl_csv(agents, filename="ghl_agents_import.csv"):
    if not agents:
        print("\n⚠️ No agents found to export.")
        return

    # GHL friendly headers
    headers = ["First Name", "Last Name", "Company Name", "Phone", "City", "Tags"]
    
    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        
        for agent in agents:
            writer.writerow({
                "First Name": agent["first_name"],
                "Last Name": agent["last_name"],
                "Company Name": agent["company_name"],
                "Phone": agent["phone"],
                "City": agent["city"],
                "Tags": "Zillow Scrape, B2B Prospect" # Auto-tag them for GHL
            })
            
    print(f"\n🎉 Successfully exported {len(agents)} agents to {filename}!")
    print("You can now upload this directly into GoHighLevel Contacts.")

if __name__ == "__main__":
    # Example: Scrape agents in Alhambra, CA
    # Change the city or add a ZIP code (e.g., "91801") to target different markets
    TARGET_LOCATION = "Alhambra CA"
    PAGES_TO_SCRAPE = 2  # Each page usually has 10-15 agents
    
    scraped_data = search_active_agents(TARGET_LOCATION, pages=PAGES_TO_SCRAPE)
    
    # Save the output
    output_file = os.path.join(os.path.dirname(__file__), 'agents_export.csv')
    export_to_ghl_csv(scraped_data, filename=output_file)
