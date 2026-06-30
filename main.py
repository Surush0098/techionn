import feedparser
import google.generativeai as genai
import requests
import time
from datetime import datetime, timedelta
from time import mktime
import os
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.1-flash-lite')
SAFE_SLEEP = 5 

HISTORY_FILE = "history.txt"

FOREIGN_URLS = [
    "https://techcrunch.com/category/startups/feed/",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/tech/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://feeds.a.dj.com/rss/RSSWSJD.xml",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?profile=120000000&id=19854910",
    "https://news.crunchbase.com/feed/",
    "https://sifted.eu/feed/",
    "https://www.eu-startups.com/feed/",
    "https://feeds.feedburner.com/venturebeat/SZYF",
    "https://www.techinasia.com/feed",
    "https://yourstory.com/feed",
    "https://www.wamda.com/rss",
    "https://www.menabytes.com/feed/",
    "https://disrupt-africa.com/feed/",
    "https://techcabal.com/feed/"
]

IRANIAN_URLS = [
    "https://digiato.com/label/startup/feed",
    "https://startup360.ir/feed",
    "https://ecomotive.ir/feed",
    "https://icheezha.ir/feed",
    "https://iranianstartup.com/feed",
    "https://itiran.com/category/startup/feed",
    "https://www.zoomit.ir/feed/"
]

ALL_URLS = FOREIGN_URLS + IRANIAN_URLS

def load_history():
    if not os.path.exists(HISTORY_FILE): return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f.readlines() if line.strip()]

def save_to_history(link, title):
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(f"{link}|{title}\n")
        os.system(f'git config --global user.name "News Bot"')
        os.system(f'git config --global user.email "bot@noreply.github.com"')
        os.system(f'git add {HISTORY_FILE}')
        os.system('git commit -m "Update history"')
        os.system('git push')
    except: pass

def check_is_duplicate_topic(new_title, history_lines):
    recent_titles = [line.split("|")[1] for line in history_lines[-200:] if len(line.split("|")) > 1]
    if not recent_titles: return False
    
    prompt = f"""
    List: {recent_titles}
    New: "{new_title}"
    Task: Check for Cross-Language Duplicates.
    Is this new title covering the SAME EVENT as any title in the list?
    Reply ONLY with YES or NO.
    """
    try:
        res = model.generate_content(prompt).text.strip().upper()
        time.sleep(SAFE_SLEEP)
        return "YES" in res
    except: 
        return False

def analyze_and_score_news(title, summary):
    prompt = f"""
    Role: Strict Venture Capital and Startup News Scout.
    Input News: "{title}"
    Summary: "{summary}"

    You MUST classify the news based on the following STARTUP ONLY categories. If the news does not clearly belong to these startup ecosystem topics, you MUST REJECT it.

    ALLOWED CATEGORIES (STARTUP ECOSYSTEM ONLY):
    - Product: Launch, Soft Launch, Beta, AI Model, API, SDK, Open Source
    - Funding & M&A: Pre-Seed to Series D+, Angel, Grants, Acquisition, Merger
    - Growth & Metrics: ARR, MRR, User Growth, Valuation, Unicorn, IPO, Delisting
    - AI & Developer: AI Agents, MCP, LLM Infrastructure, Frameworks, DevTools, Cloud
    - Business: Strategic Partnerships, Enterprise Deals, Government Contracts
    - Founders & Startups: Founder Story, Success, Failures, Layoffs, Shutdowns, Pivots
    - VC & Accelerators: New Funds, YC, Techstars, Portfolio Announcements
    - Ecosystem & Industry: Market Reports, Web3, FinTech, HealthTech, SaaS, BioTech

    STRICT REJECTION (REJECT IF MATCHES):
    - Gold prices, stock market general news, forex, crypto coin prices.
    - Smartphone, PC, Laptop, Hardware or Gadget reviews/rumors.
    - General consumer app updates.
    - E-commerce sales, discounts, festivals, and promotional campaigns.
    - Political news, general government news, or local corporate gossip.
    - Any general tech news not directly tied to the startup, VC, or software-builder ecosystem.

    OUTPUT FORMAT ONLY: VIP | NORMAL | REJECT
    """
    try:
        response = model.generate_content(prompt).text.strip().upper()
        time.sleep(SAFE_SLEEP)
        if "VIP" in response: return "VIP"
        elif "NORMAL" in response: return "NORMAL"
        else: return "REJECT"
    except: return "REJECT"

def generate_content(title, content, category, is_foreign):
    fixed_hashtag = "#نیوز" if is_foreign else "#خبر"
    
    if is_foreign:
        style_instr = "Read the story and RETELL it in formal, professional Persian. Do NOT translate word-for-word."
    else:
        style_instr = "Rewrite the text in formal, professional Persian."

    length_instr = "Write 5 to 11 lines." if category == "VIP" else "Write 4 to 7 lines."

    prompt = f"""
    Role: Senior Tech Journalist for a formal News Channel (@techionn).
    Original Title: {title}
    Content: {content}
    
    Task:
    1. **Headline:** Start immediately with a BOLD, professional Persian headline.
    2. **Body:** {style_instr}
       - {length_instr}
       - Tone: **Formal, Professional, News-style.**
       - **STRICTLY FORBIDDEN:** Do NOT use greetings. Do NOT use slang or casual street language.
       - Start the text directly with the news facts.
       - **Smart Context:** If mentioning an unknown startup, add a footer line with '💡' explaining it briefly.
    3. **Hashtags:** - Add exactly 3 hashtags at the end.
       - First one MUST be: {fixed_hashtag}
       - Generate 2 other relevant hashtags in Persian.
    4. **Footer:** End with: 🆔 @techionn
    """
    try:
        res = model.generate_content(prompt).text
        time.sleep(SAFE_SLEEP)
        return res
    except: return None

def extract_image(entry):
    try:
        if 'media_content' in entry: return entry.media_content[0]['url']
        if 'links' in entry:
            for l in entry.links:
                if l.type.startswith('image/') and 'href' in l: return l.href
        
        content_to_parse = ""
        if 'content' in entry: content_to_parse += entry.content[0].value
        if 'summary' in entry: content_to_parse += entry.summary
            
        if content_to_parse:
            soup = BeautifulSoup(content_to_parse, 'html.parser')
            images = soup.find_all('img')
            for img in images:
                if 'src' in img.attrs:
                    src = img['src']
                    if 'icon' not in src and 'emoji' not in src: return src
    except: pass
    return None

def send_to_telegram(message, image_url=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/" + ("sendPhoto" if image_url else "sendMessage")
        data = {"chat_id": CHANNEL_ID, "parse_mode": "Markdown"}
        if image_url:
            data["photo"] = image_url
            data["caption"] = message
        else:
            data["text"] = message
        requests.post(url, data=data)
    except: pass

def check_feeds():
    history_lines = load_history()
    history_links = [line.split("|")[0] for line in history_lines]
    
    time_threshold = datetime.now() - timedelta(hours=4)
    
    for url in ALL_URLS:
        try:
            is_foreign = url in FOREIGN_URLS
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed'):
                    pub_date = datetime.fromtimestamp(mktime(entry.published_parsed))
                    
                    if pub_date > time_threshold:
                        if entry.link in history_links: continue
                        
                        text_analysis = entry.summary if 'summary' in entry else entry.title
                        category = analyze_and_score_news(entry.title, text_analysis)
                        
                        if category == "REJECT": continue
                        
                        if check_is_duplicate_topic(entry.title, history_lines):
                            save_to_history(entry.link, entry.title)
                            continue
                        
                        full_content = entry.content[0].value if 'content' in entry else entry.summary
                        summary = generate_content(entry.title, full_content, category, is_foreign)
                        
                        if summary:
                            send_to_telegram(summary, extract_image(entry))
                            save_to_history(entry.link, entry.title)
                            
        except: pass

if __name__ == "__main__":
    check_feeds()
