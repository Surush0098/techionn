import feedparser
import google.generativeai as genai
import requests
import time
from datetime import datetime, timedelta
from time import mktime
import os
from bs4 import BeautifulSoup

# --- کلیدهای پروژه جدید ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# تنظیمات مدل
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-lite')
SAFE_SLEEP = 5  # مکث ایمنی

HISTORY_FILE = "history.txt"

# --- لیست منابع ---
# خارجی‌ها
FOREIGN_URLS = [
    "https://techcrunch.com/feed/", 
    "https://feeds.feedburner.com/venturebeat/SZYF",
    "https://www.theverge.com/rss/index.xml",
]

# ایرانی‌ها (حتما تهش feed یا rss اضافه کردم که کار کنه)
IRANIAN_URLS = [
    "https://digiato.com/label/startup/feed",
    "https://startup360.ir/feed",
    "https://ecomotive.ir/feed",
    "https://icheezha.ir/feed",
    "https://iranianstartup.com/feed",
    "https://itiran.com/category/startup/feed",
    "https://www.zoomit.ir/feed/",
]

# ترکیب همه برای حلقه اصلی
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
    # افزایش حافظه به 200 خبر آخر (برای پوشش تاخیر سایت‌های ایرانی)
    recent_titles = [line.split("|")[1] for line in history_lines[-200:] if len(line.split("|")) > 1]
    if not recent_titles: return False
    
    prompt = f"""
    I have a list of recent news titles (some English, some Persian):
    {recent_titles}

    New News Title: "{new_title}"

    Task: Check for Cross-Language Duplicates.
    If the new title is covering the SAME EVENT as any title in the list (even if one is English and the other is Persian), reply YES.
    
    Example: "Snapp raised funds" (English) AND "اسنپ سرمایه جذب کرد" (Persian) -> YES.
    
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
    Role: Strict Venture Capital (VC) Scout.
    News: "{title}"
    Summary: "{summary}"

    Categorize this news:

    --- VIP (Must Publish) ---
    1. Fundraising / Investment / VC deals.
    2. M&A (Acquisitions), IPOs, Exits.
    3. Innovative Ideas / Early-stage Startups.
    4. Market Statistics (Growth reports).
    5. Obscure/Small country startups raising money.
    6. Financial earnings of TECH startups.

    --- NORMAL (Score > 70) ---
    1. Major tech shifts (AI breakthroughs like GPT-5).
    2. Strategic business moves (Not simple HR).
    
    --- REJECT (Trash) ---
    1. Gadget reviews (Phones, Laptops).
    2. App updates/features.
    3. General corporate HR (CEO change of known giants is boring unless controversial).
    4. Political gossip.
    5. General science/space/movie reviews.

    OUTPUT: VIP | NORMAL | REJECT
    """
    try:
        response = model.generate_content(prompt).text.strip()
        time.sleep(SAFE_SLEEP)
        if "VIP" in response: return "VIP"
        elif "NORMAL" in response: return "NORMAL"
        else: return "REJECT"
    except: return "REJECT"

def generate_content(title, content, category, is_foreign):
    # تعیین طول متن
    length_instr = "Detailed summary (5-11 lines)" if category == "VIP" else "Concise summary (4-7 lines)"
    
    # دستور ترجمه یا بازنویسی
    if is_foreign:
        action_instr = "1. Translate to fluent Persian."
    else:
        action_instr = "1. Rewrite in fluent Persian (improve the text)."

    prompt = f"""
    Role: Tech Editor for a Startup Channel.
    News: {title}
    Content: {content}
    
    Task:
    {action_instr}
    2. {length_instr}.
    3. Tone: Professional, VC-style, Exciting.
    4. **Smart Context:** If the startup/company is unknown to Iranians, add a footer line with '💡' explaining what they do. If famous, DO NOT add it.
    5. NO links.
    6. End with: 🆔 @YourNewChannelID
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
                if l.type.startswith('image/'): return l.href
        content_to_parse = entry.content[0].value if 'content' in entry else entry.summary
        soup = BeautifulSoup(content_to_parse, 'html.parser')
        img = soup.find('img')
        if img and 'src' in img.attrs: return img['src']
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
    
    # بازه زمانی 150 دقیقه (2.5 ساعت)
    time_threshold = datetime.now() - timedelta(minutes=150)
    
    for url in ALL_URLS:
        try:
            # تشخیص اینکه آیا سایت خارجی است یا ایرانی
            is_foreign = url in FOREIGN_URLS
            
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed'):
                    pub_date = datetime.fromtimestamp(mktime(entry.published_parsed))
                    
                    if pub_date > time_threshold:
                        if entry.link in history_links: continue
                        
                        # آنالیز و نمره دهی
                        text_for_analysis = entry.summary if 'summary' in entry else entry.title
                        category = analyze_and_score_news(entry.title, text_for_analysis)
                        
                        if category == "REJECT":
                            print(f"Rejected: {entry.title}")
                            continue
                        
                        # چک تکراری (شامل چک دوزبانه)
                        if check_is_duplicate_topic(entry.title, history_lines):
                            print(f"Duplicate Topic: {entry.title}")
                            save_to_history(entry.link, entry.title)
                            continue
                        
                        # تولید محتوا
                        full_content = entry.content[0].value if 'content' in entry else entry.summary
                        summary = generate_content(entry.title, full_content, category, is_foreign)
                        
                        if summary:
                            icon = "💎" if category == "VIP" else "🚀"
                            # اگر خارجی بود، تیتر انگلیسی رو نشون نده، فقط متن فارسی
                            # اگر ایرانی بود، همون تیتر خودش رو بذار
                            display_title = entry.title
                            
                            final_text = f"{icon} **{display_title}**\n\n{summary}"
                            
                            send_to_telegram(final_text, extract_image(entry))
                            save_to_history(entry.link, entry.title)
                            
        except Exception as e: print(f"Feed Error: {e}")

if __name__ == "__main__":
    check_feeds()
