# main.py
# Requirements: pip install telethon requests python-dotenv
import os
import re
import time
import asyncio
import logging
import json # MODIFIED: Added json import
import sqlite3
import requests
from telethon import TelegramClient, events
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

# ========== Load Environment Variables ==========
load_dotenv()

# ========== CONFIG ==========
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SESSION_NAME = "session"
OPENROUTER_MODEL = "google/gemma-3-27b-it"
DELAY_BETWEEN_CALLS_SECONDS = 60
MEDIA_DIR = "media_cache"
os.makedirs(MEDIA_DIR, exist_ok=True)

if not all([API_ID, API_HASH, OPENROUTER_API_KEY]):
    raise ValueError("API_ID, API_HASH, and OPENROUTER_API_KEY must be set in your .env file.")

# ========== Rotating Log Configuration ==========
LOG_FILE = "translator.log"
log_handler = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=5, encoding='utf-8')
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(funcName)s] %(message)s",
    handlers=[
        log_handler,
        logging.StreamHandler()
    ]
)
log = logging.getLogger("tg-multi-translator")


# ========== NEW: Load Channel Mappings from JSON file ==========
def load_channel_mappings():
    """Loads channel mappings from channels.json and handles errors."""
    try:
        with open("channels.json", "r", encoding="utf-8") as f:
            mappings = json.load(f)
            log.info("Loaded %d channel mappings from channels.json", len(mappings))
            return mappings
    except FileNotFoundError:
        log.critical("FATAL: channels.json not found! Please create it.")
        # Create a template file to help the user
        with open("channels.json", "w", encoding="utf-8") as f:
            template = {"source_channel_username": "destination_channel_username"}
            json.dump(template, f, indent=4)
        log.info("An example channels.json has been created for you.")
        exit()
    except json.JSONDecodeError:
        log.critical("FATAL: Could not parse channels.json. Please check for syntax errors (e.g., missing commas).")
        exit()

# MODIFIED: Load mappings from the function instead of a hardcoded dict
CHANNEL_MAPPINGS = load_channel_mappings()


# ========== DB ==========
DB_PATH = "processed_messages.db"
processed_in_session = set()

def init_db(path=DB_PATH):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS processed (channel TEXT, msg_id INTEGER, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(channel,msg_id))"
    )
    conn.commit()
    return conn

def prune_old_records(conn, days_to_keep=7):
    """Deletes records from the database older than a specified number of days."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        cur = conn.cursor()
        cur.execute("DELETE FROM processed WHERE processed_at < ?", (cutoff_date,))
        conn.commit()
        log.info("Pruned %d old records from the database.", cur.rowcount)
    except Exception as e:
        log.error("Failed to prune old database records: %s", e)

def is_processed(conn, ch, mid):
    if (ch, mid) in processed_in_session:
        return True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM processed WHERE channel=? AND msg_id=?", (str(ch), int(mid)))
    return cur.fetchone() is not None

def mark_processed(conn, ch, mid):
    processed_in_session.add((ch, mid))
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO processed(channel, msg_id) VALUES(?,?)", (str(ch), int(mid)))
    conn.commit()

# ========== TELETHON & CONCURRENCY ==========
client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
llm_semaphore = asyncio.Semaphore(1)


# ========== URL MASKING & TRANSLATION (No changes here) ==========
URL_RE = re.compile(r'https?://\S+')
def mask_urls(text):
    urls = URL_RE.findall(text or "")
    mapping = {}
    masked = text or ""
    for i, url in enumerate(urls):
        token = f"<URL{i}>"
        masked = masked.replace(url, token, 1)
        mapping[token] = url
    return masked, mapping

def restore_urls(text, mapping):
    if not mapping: return text
    for token, url in mapping.items():
        text = text.replace(token, url)
    return text

def call_openrouter_sync(prompt, max_tokens=800, temperature=0.15, retries=3):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    body = {"model": OPENROUTER_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": temperature}
    backoff = 2
    for attempt in range(1, retries + 1):
        try:
            log.info("OpenRouter request -> model=%s attempt=%s", OPENROUTER_MODEL, attempt)
            r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, timeout=60)
            if r.status_code == 429:
                log.warning("OpenRouter 429. sleeping %s sec", backoff); time.sleep(backoff); backoff *= 2; continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            log.warning("OpenRouter request error attempt %s: %s", attempt, e)
            if attempt == retries: raise
            time.sleep(backoff); backoff *= 2
    return None

def extract_text_from_openrouter(resp_json):
    try:
        return resp_json["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        log.warning("Can't extract OpenRouter output: %s", json.dumps(resp_json)[:800])
        return None

PROMPT_TEMPLATE = (
    "You are an expert translator, converting text for a Telegram channel into natural-sounding Japanese (JLPT N3 level).\n"
    "Your main task is to translate the text while perfectly formatting it for Telegram's HTML parse mode.\n\n"
    "**CRITICAL INSTRUCTIONS:**\n\n"
    "1.  **Handle Links (`<URL...>`):**\n"
    "    - The input contains placeholders like `<URL0>`, `<URL1>`, etc. These are located near the words they correspond to.\n"
    "    - In your Japanese translation, you MUST identify the most logical word or phrase to be the clickable link text.\n"
    "    - You MUST format these links using HTML `<a>` tags. Example: `<a href=\"<URL0>\">適切な日本語テキスト</a>`.\n"
    "    - **NEVER** leave a `<URL...>` token as plain text in the output. It must ONLY exist inside an `href` attribute.\n\n"
    "2.  **Handle Formatting:**\n"
    "    - The input may use `<b>text</b>` for bold. Preserve this HTML tag in your translation around the corresponding translated words.\n\n"
    "3.  **Output:**\n"
    "    - Your entire output must be ONLY the final, translated Japanese text. Do not add any extra explanations or greetings.\n\n"
    "--- EXAMPLE ---\n"
    "INPUT: \"Проект <b>Qwen3-Omni</b> (<URL0>) доступен на GitHub (<URL1>).\"\n"
    "CORRECT OUTPUT: \"<b>Qwen3-Omni</b>プロジェクトは<a href=\"<URL1>\">GitHub</a>で公開されています。(<a href=\"<URL0>\">https://chat.qwen.ai...</a>)\" (Note: LLM may choose how to best place the link)\n"
    "--- END EXAMPLE ---\n\n"
    "**Input text to translate:**\n"
    "\"\"\"{input_text}\"\"\""
)

def translate_text_sync(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    masked, mapping = mask_urls(text)
    prompt = PROMPT_TEMPLATE.format(input_text=masked)
    j = call_openrouter_sync(prompt)
    out = extract_text_from_openrouter(j) if j else None
    
    if out:
        out = restore_urls(out, mapping)
        markdown_link_pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)\)*')
        out = markdown_link_pattern.sub(r'<a href="\2">\1</a>', out)
    return out

# ========== MEDIA HELPERS (No changes here) ==========
async def download_media_safe(msg, out_dir, prefix):
    try:
        safe_prefix = re.sub(r'[\\/*?:"<>|]', "", prefix)
        fname = os.path.join(out_dir, f"{safe_prefix}_{msg.id}")
        path = await client.download_media(msg, file=fname)
        return path
    except Exception as e:
        log.warning("download_media failed for %s: %s", getattr(msg, "id", None), e)
    return None

async def send_post_with_media(target, media_paths, caption):
    try:
        if not media_paths:
            await client.send_message(target, caption, parse_mode='html')
        elif len(media_paths) == 1:
            await client.send_file(target, media_paths[0], caption=caption, parse_mode='html')
        else:
            await client.send_file(target, media_paths, caption=caption, parse_mode='html')
        return True
    except Exception as e:
        log.warning("send_file to %s failed: %s", target, e)
        return False

# ========== POST PROCESSING (No changes here) ==========
async def process_post(conn, source_channel, target_channel, post_key, all_messages_in_group):
    caption_text = ""
    for m in sorted(all_messages_in_group, key=lambda msg: msg.id):
        if m.text:
            caption_text += m.text.strip() + "\n\n"
    caption_text = caption_text.strip()
    
    media_msgs = [m for m in all_messages_in_group if getattr(m, "media", None)]

    if not caption_text:
        log.info("Post %s from @%s has no text. Marking processed.", post_key, source_channel)
        mark_processed(conn, source_channel, post_key)
        return

    if source_channel == "black_triangle_tg":
        caption_text = re.sub(r'\s*\([^)]*https?://[^)]+\)', '', caption_text).strip()

    log.info("Processing post %s from @%s: %s", post_key, source_channel, caption_text[:120])
    
    ad_keywords = ["#реклама", "Реклама.", "#промо"]
    if any(keyword in caption_text for keyword in ad_keywords):
        log.info("Post %s is an advertisement. Skipping.", post_key)
        mark_processed(conn, source_channel, post_key)
        return

    translated = None
    async with llm_semaphore:
        log.info("Acquired LLM semaphore for @%s post %s", source_channel, post_key)
        translated = await asyncio.to_thread(translate_text_sync, caption_text)
    
    if not translated:
        log.error("Translation failed for post %s from @%s", post_key, source_channel)
        asyncio.create_task(delay_after_llm_call())
        return

    header = f"From @{source_channel} • id {post_key}\n\n"
    final_caption = header + translated
    
    media_paths = [p for m in media_msgs if (p := await download_media_safe(m, MEDIA_DIR, f"{source_channel}_{post_key}"))]
    
    ok = await send_post_with_media(target_channel, media_paths, final_caption)
    if ok:
        mark_processed(conn, source_channel, post_key)
        log.info("Successfully posted and marked processed: @%s post %s", source_channel, post_key)
    else:
        log.warning("FAILED to send post %s from @%s to %s.", post_key, source_channel, target_channel)

    for p in media_paths:
        try: os.remove(p)
        except OSError as e: log.warning("Failed to remove media file %s: %s", p, e)
    
    await delay_after_llm_call()

async def delay_after_llm_call():
    log.info("Waiting for %d seconds before next translation...", DELAY_BETWEEN_CALLS_SECONDS)
    await asyncio.sleep(DELAY_BETWEEN_CALLS_SECONDS)

# ========== NEW EVENT HANDLER ==========
@events.register(events.NewMessage(chats=list(CHANNEL_MAPPINGS.keys())))
async def new_message_handler(event):
    conn = event.client.db_conn
    # Check if the source channel exists in our mappings before processing
    if event.chat.username not in CHANNEL_MAPPINGS:
        return
    
    target_channel = CHANNEL_MAPPINGS[event.chat.username]
    source_channel = event.chat.username
    message = event.message
    post_key = message.grouped_id or message.id
    
    if is_processed(conn, source_channel, post_key):
        log.debug("Post key %s from @%s already processed or in session, skipping.", post_key, source_channel)
        return

    log.info("New event for post key %s from @%s", post_key, source_channel)
    
    mark_processed(conn, source_channel, post_key)

    all_messages_in_group = []
    if message.grouped_id:
        try:
            all_messages_in_group = await client.get_messages(event.chat, limit=20, ids=range(message.id - 10, message.id + 10))
            all_messages_in_group = [m for m in all_messages_in_group if m and m.grouped_id == message.grouped_id]
        except Exception as e:
            log.error("Could not fetch message group for key %s: %s", post_key, e)
            all_messages_in_group = [message]
    else:
        all_messages_in_group = [message]

    asyncio.create_task(process_post(conn, source_channel, target_channel, post_key, all_messages_in_group))

# ========== Background task for cleanup ==========
async def daily_cleanup_task(conn):
    """Runs every 24 hours to clean up old data."""
    while True:
        await asyncio.sleep(24 * 60 * 60)
        log.info("Running daily cleanup task...")
        prune_old_records(conn)

# ========== MAIN ==========
async def main():
    db_conn = init_db()
    client.db_conn = db_conn
    
    log.info("Client starting...")
    await client.start()
    log.info("Client started. Event handler is now active.")
    
    asyncio.create_task(daily_cleanup_task(db_conn))
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        client.on(events.NewMessage(chats=list(CHANNEL_MAPPINGS.keys())))(new_message_handler)
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        log.info("Interrupted by user. Shutting down.")
    finally:
        log.info("Stopped.")