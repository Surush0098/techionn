import feedparser
import google.generativeai as genai
import requests
import time
from datetime import datetime, timedelta
from time import mktime
import os
from bs4 import BeautifulSoup

# --- کلیدها ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# تنظیمات مدل
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-lite')
SAFE_SLEEP = 5 

HISTORY_FILE = "history.txt"

# --- منابع ---
FOREIGN_URLS = [
    "https://techcrunch.com/category/startups/feed/",
    "https://feeds.feedburner.com/venturebeat/SZYF",
    "https://www.theverge.com/rss/index.xml",
]

IRANIAN_URLS = [
    "https://digiato.com/label/startup/feed",
    "https://startup360.ir/feed",
    "https://ecomotive.ir/feed",
    "https://icheezha.ir/feed",
    "https://iranianstartup.com/feed",
    "https://itiran.com/category/startup/feed",
    "https://www.zoomit.ir/feed/",
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
    Role: Strict Venture Capital (VC) Scout.
    Input News: "{title}"
    Summary: "{summary}"

    Categorize based on these rules:

    --- VIP (Must Publish) 💎 ---
    1. Fundraising / Investment (Series A, B, IPO, M&A).
    2. Innovative Ideas / Early-stage Startups.
    3. Market Statistics / Growth Reports.
    4. Obscure/Small country startups raising money.

    --- NORMAL (Publish) 🔥 ---
    1. Major Tech Shifts (AI breakthroughs).
    2. Strategic Business Moves (Not simple HR).

    --- REJECT (Do Not Publish) 🗑️ ---
    1. Gadget Reviews (Phones, Laptops).
    2. App Updates/Features.
    3. Corporate HR / CEO Change (Unless controversial).
    4. Political Gossip.
    5. Sales Festivals / Ads.

    OUTPUT FORMAT ONLY: VIP | NORMAL | REJECT
    """
    try:
        response = model.generate_content(prompt).text.strip()
        time.sleep(SAFE_SLEEP)
        if "VIP" in response: return "VIP"
        elif "NORMAL" in response: return "NORMAL"
        else: return "REJECT"
    except: return "REJECT"

def generate_content(title, content, category, is_foreign):
    # تعیین نوع هشتگ ثابت بر اساس منبع
    fixed_hashtag = "#نیوز" if is_foreign else "#خبر"
    
    # دستورالعمل برای خارجی‌ها (قصه‌گویی) یا ایرانی‌ها (بازنویسی)
    if is_foreign:
        style_instr = "Do NOT translate word-for-word. Read the story, understand it, and RETELL it in fluent, engaging Persian (Storytelling mode)."
    else:
        style_instr = "Rewrite the text in fluent, engaging Persian. Make it punchy and interesting."

    # تعیین طول متن
    length_instr = "Write 5 to 11 lines." if category == "VIP" else "Write 4 to 7 lines."

    prompt = f"""
    Role: Tech Storyteller for @techionn.
    Original Title: {title}
    Content: {content}
    
    Task:
    1. **Headline:** Start with a BOLD Persian headline (catchy and relevant). Do NOT use the English title.
    2. **Body:** {style_instr}
       - {length_instr}
       - Tone: Friendly, insightful, like a tech vlogger explaining to a friend.
       - **FORBIDDEN:** Do NOT use words like "خلاصه", "ترجمه", "متن خبر". Just dive into the story.
       - **Smart Context:** If mentioning an unknown startup/company, add a footer line with '💡' explaining it briefly.
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
    """استخراج قوی‌تر عکس"""
    try:
        # اولویت 1: مدیا کانتنت (استاندارد RSS)
        if 'media_content' in entry: 
            return entry.media_content[0]['url']
        
        # اولویت 2: لینک‌های ضمیمه (Enclosures)
        if 'links' in entry:
            for l in entry.links:
                if l.type.startswith('image/') and 'href' in l:
                    return l.href
        
        # اولویت 3: جستجو در محتوای HTML
        content_to_parse = ""
        if 'content' in entry:
            content_to_parse += entry.content[0].value
        if 'summary' in entry:
            content_to_parse += entry.summary
            
        if content_to_parse:
            soup = BeautifulSoup(content_to_parse, 'html.parser')
            # پیدا کردن اولین عکس معتبر
            images = soup.find_all('img')
            for img in images:
                if 'src' in img.attrs:
                    # فیلتر کردن آیکون‌های کوچک یا ایموجی‌ها
                    src = img['src']
                    if 'icon' not in src and 'emoji' not in src:
                        return src
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
    
    # 150 دقیقه قبل
    time_threshold = datetime.now() - timedelta(minutes=150)
    
    print("Checking feeds...")
    
    for url in ALL_URLS:
        try:
            is_foreign = url in FOREIGN_URLS
            
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed'):
                    pub_date = datetime.fromtimestamp(mktime(entry.published_parsed))
                    
                    if pub_date > time_threshold:
                        if entry.link in history_links: continue
                        
                        # آنالیز
                        text_analysis = entry.summary if 'summary' in entry else entry.title
                        category = analyze_and_score_news(entry.title, text_analysis)
                        
                        if category == "REJECT":
                            print(f"Rejected: {entry.title}")
                            continue
                        
                        # چک تکراری
                        if check_is_duplicate_topic(entry.title, history_lines):
                            save_to_history(entry.link, entry.title)
                            continue
                        
                        # تولید محتوا
                        full_content = entry.content[0].value if 'content' in entry else entry.summary
                        summary = generate_content(entry.title, full_content, category, is_foreign)
                        
                        if summary:
                            # آیکون برای لاگ یا دیباگ (در تلگرام نشون داده نمیشه چون تو متن خود هوش مصنوعیه)
                            # ما اینجا مستقیم خروجی هوش مصنوعی رو میفرستیم که خودش تیتر داره
                            
                            send_to_telegram(summary, extract_image(entry))
                            print(f"Sent: {entry.title}")
                            save_to_history(entry.link, entry.title)
                            
        except Exception as e: print(f"Error: {e}")

if __name__ == "__main__":
    check_feeds()
