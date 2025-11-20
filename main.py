import feedparser
import google.generativeai as genai
import requests
import time
from datetime import datetime, timedelta
from time import mktime
import os
from bs4 import BeautifulSoup

# --- تنظیمات و دریافت کلیدها از گیت‌هاب ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# تنظیمات مدل هوش مصنوعی
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-lite')
SAFE_SLEEP = 5  # مکث 5 ثانیه‌ای بین درخواست‌ها (جلوگیری از بلاک شدن)

HISTORY_FILE = "history.txt"

# --- لیست منابع خبری ---

# منابع خارجی (نیاز به ترجمه)
FOREIGN_URLS = [
    "https://techcrunch.com/category/startups/feed/",
    "https://feeds.feedburner.com/venturebeat/SZYF",
    "https://www.theverge.com/rss/index.xml",
]

# منابع ایرانی (نیاز به بازنویسی و فیلتر دقیق)
IRANIAN_URLS = [
    "https://digiato.com/label/startup/feed",
    "https://startup360.ir/feed",
    "https://ecomotive.ir/feed",
    "https://icheezha.ir/feed",
    "https://iranianstartup.com/feed",
    "https://itiran.com/category/startup/feed",
    "https://www.zoomit.ir/feed/",
]

# ترکیب همه لینک‌ها
ALL_URLS = FOREIGN_URLS + IRANIAN_URLS

def load_history():
    """خواندن تاریخچه لینک‌های ارسال شده"""
    if not os.path.exists(HISTORY_FILE): return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f.readlines() if line.strip()]

def save_to_history(link, title):
    """ذخیره لینک جدید در تاریخچه"""
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(f"{link}|{title}\n")
        # دستورات گیت برای ذخیره دائمی در سرور
        os.system(f'git config --global user.name "News Bot"')
        os.system(f'git config --global user.email "bot@noreply.github.com"')
        os.system(f'git add {HISTORY_FILE}')
        os.system('git commit -m "Update history"')
        os.system('git push')
    except: pass

def check_is_duplicate_topic(new_title, history_lines):
    """
    تشخیص تکراری بودن موضوع (حتی بین فارسی و انگلیسی)
    """
    # 200 خبر آخر را چک میکنیم تا مچ سایت‌های ایرانی کپی‌کار را بگیریم
    recent_titles = [line.split("|")[1] for line in history_lines[-200:] if len(line.split("|")) > 1]
    if not recent_titles: return False
    
    prompt = f"""
    I have a list of recent news titles (English & Persian):
    {recent_titles}

    New News Title: "{new_title}"

    Task: Check for Cross-Language Duplicates.
    Is this new title covering the SAME EVENT as any title in the list?
    (e.g., "OpenAI launched GPT-5" == "OpenAI از GPT-5 رونمایی کرد" -> YES)
    
    Reply ONLY with YES or NO.
    """
    try:
        res = model.generate_content(prompt).text.strip().upper()
        time.sleep(SAFE_SLEEP)
        return "YES" in res
    except: 
        return False

def analyze_and_score_news(title, summary):
    """
    آنالیز ارزش خبری: تفکیک الماس (VIP) از زباله (Reject)
    با دستورات دو زبانه برای دقت روی سایت‌های ایرانی
    """
    prompt = f"""
    Role: Strict Venture Capital (VC) Scout.
    Input News: "{title}"
    Summary: "{summary}"

    Analyze the meaning regardless of language (Persian/English).
    Categorize based on these rules:

    --- VIP (Must Publish) 💎 ---
    1. Fundraising / Investment (جذب سرمایه، راند سرمایه‌گذاری).
    2. M&A / IPO / Exits (خرید سهام، ادغام، عرضه در بورس).
    3. Innovative Early-stage Startups (ایده‌های نو و استارتاپ‌های جدید).
    4. Market Statistics / Growth Reports (گزارش بازار، آمار رشد).
    5. Obscure/Small country startups raising money.

    --- NORMAL (Publish) 🔥 ---
    1. Major Tech Shifts (e.g., AI breakthroughs like GPT-5).
    2. Strategic Business Moves (تغییرات استراتژیک کسب‌وکار).

    --- REJECT (Do Not Publish) 🗑️ ---
    1. Gadget Reviews (بررسی موبایل، لپ‌تاپ، مقایسه).
    2. App Updates/Features (آپدیت معمولی، دارک مود).
    3. Corporate HR / CEO Change (تغییر مدیرعامل شرکت‌های معروف و بزرگ - مگر اینکه خیلی جنجالی باشد).
    4. Political Gossip (شایعات سیاسی).
    5. Sales Festivals / Ads (جشنواره فروش، یلدا، بلک فرایدی).

    OUTPUT FORMAT ONLY: VIP | NORMAL | REJECT
    """
    try:
        response = model.generate_content(prompt).text.strip()
        time.sleep(SAFE_SLEEP)
        
        if "VIP" in response: return "VIP"
        elif "NORMAL" in response: return "NORMAL"
        else: return "REJECT"
    except:
        return "REJECT"

def generate_content(title, content, category, is_foreign):
    """
    تولید متن نهایی (ترجمه یا بازنویسی)
    """
    # تعیین طول متن بر اساس اهمیت
    length_instr = "Detailed summary (5-11 lines)" if category == "VIP" else "Concise summary (4-7 lines)"
    
    # اگر خارجی بود ترجمه، اگر ایرانی بود بازنویسی
    action_instr = "Translate to fluent Persian." if is_foreign else "Rewrite in fluent Persian (improve text)."

    prompt = f"""
    Role: Tech Editor for a Startup Channel (@techionn).
    News: {title}
    Content: {content}
    
    Task:
    1. {action_instr}
    2. {length_instr}.
    3. Tone: Professional, VC-style, Exciting.
    4. **Smart Context:** If the startup/company is unknown to Iranians (e.g., a small French AI startup), add a footer line with '💡' explaining what they do. If famous (Snapp, Digikala, Apple), DO NOT add it.
    5. NO links in text.
    6. End with: 🆔 @techionn
    """
    try:
        res = model.generate_content(prompt).text
        time.sleep(SAFE_SLEEP)
        return res
    except: return None

def extract_image(entry):
    """استخراج عکس از منابع مختلف"""
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
    """ارسال به کانال تلگرام"""
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
    """تابع اصلی بررسی سایت‌ها"""
    history_lines = load_history()
    history_links = [line.split("|")[0] for line in history_lines]
    
    # بررسی 150 دقیقه (2.5 ساعت) اخیر برای اطمینان از جا نماندن خبرها
    time_threshold = datetime.now() - timedelta(minutes=150)
    
    print("Start checking feeds...")
    
    for url in ALL_URLS:
        try:
            # تشخیص اینکه آیا سایت خارجی است یا ایرانی
            is_foreign = url in FOREIGN_URLS
            
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed'):
                    pub_date = datetime.fromtimestamp(mktime(entry.published_parsed))
                    
                    if pub_date > time_threshold:
                        # 1. چک کردن لینک تکراری
                        if entry.link in history_links: continue
                        
                        # 2. آنالیز و نمره دهی (VIP یا REJECT)
                        text_for_analysis = entry.summary if 'summary' in entry else entry.title
                        category = analyze_and_score_news(entry.title, text_for_analysis)
                        
                        if category == "REJECT":
                            print(f"Rejected: {entry.title}")
                            continue
                        
                        # 3. چک کردن موضوع تکراری (بین زبانی)
                        if check_is_duplicate_topic(entry.title, history_lines):
                            print(f"Duplicate Topic: {entry.title}")
                            save_to_history(entry.link, entry.title)
                            continue
                        
                        # 4. تولید محتوا
                        full_content = entry.content[0].value if 'content' in entry else entry.summary
                        summary = generate_content(entry.title, full_content, category, is_foreign)
                        
                        if summary:
                            # آیکون متفاوت برای خبرهای VIP
                            icon = "💎" if category == "VIP" else "🚀"
                            
                            # برای سایت‌های خارجی فقط متن فارسی، برای ایرانی تیتر خودش
                            display_title = entry.title
                            
                            final_text = f"{icon} **{display_title}**\n\n{summary}"
                            
                            send_to_telegram(final_text, extract_image(entry))
                            print(f"Sent: {entry.title}")
                            save_to_history(entry.link, entry.title)
                            
        except Exception as e: print(f"Feed Error: {e}")

if __name__ == "__main__":
    check_feeds()
