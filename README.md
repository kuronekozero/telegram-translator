# Telegram Multi-Channel AI Translator

[![Buy Me A Coffee](https://img.shields.io/badge/☕-Buy%20me%20a%20coffee-yellow?style=flat-square)](https://www.buymeacoffee.com/kur0)  

A Python-based bot that automatically monitors specified public Telegram channels, translates new posts using an AI model via OpenRouter, and forwards them to designated private channels.

This project is primarily designed for language learners who want a consistent stream of reading practice material from topics they find interesting. It is configured out-of-the-box to translate Russian/English text to Japanese (JLPT N3 level), but can be easily adapted for any language pair by changing LLM prompt inside of the main.py file.

***

## Table of Contents
- [How It Works](#how-it-works)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Setup Instructions](#setup-instructions)
- [Running the Bot](#running-the-bot)
  - [Using the .bat Scripts (Windows)](#using-the-bat-scripts-windows)
  - [First-Time Run & Telegram Login](#first-time-run--telegram-login)
  - [Important: Which Telegram Account to Use](#important-which-telegram-account-to-use)
  - [Autostart on Windows Startup](#autostart-on-windows-startup)
- [Configuration](#configuration)
  - [API Keys (`.env`)](#api-keys-env)
  - [Channel Mappings (`channels.json`)](#channel-mappings-channelsjson)
  - [Customizing the Translation](#customizing-the-translation)
  - [Personal Preferences](#personal-preferences)
- [LLM & Cost Recommendations](#llm--cost-recommendations)
- [Future Plans & Known Issues](#future-plans--known-issues)
- [License](#license)

***

## How It Works

The bot uses a combination of several components to achieve its goal:

* **Telethon**: A Python library to interact with the Telegram API. It's used to monitor the source channels for new messages in real-time.
* **OpenRouter API**: Acts as a gateway to various large language models (LLMs). This project uses it to send the text from new posts for translation.
* **SQLite Database**: A lightweight local database is used to keep track of which posts have already been processed, preventing duplicate translations and forwards, even if the bot is restarted.
* **Configuration Files**: The bot is configured using external files (`.env`, `channels.json`) to keep secret keys and settings separate from the core application logic.

***

## Getting Started

Follow these instructions to get a copy of the project up and running on your local machine.

### Prerequisites

* Python 3.8+
* **Telegram API Credentials**: An `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org).
* **OpenRouter API Key**: An account and API key from [OpenRouter.ai](https://openrouter.ai/).

### Setup Instructions

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/kuronekozero/telegram-translator.git
    cd telegram-translator
    ```

2.  **Install Python dependencies:**
    ```bash
    # It's recommended to do this inside a virtual environment
    pip install -r requirements.txt
    ```

3.  **Configure API Keys**: Open the template `.env` file that comes with the project. Replace the placeholder values with your actual secret keys.
    ```env
    # .env
    API_ID="YOUR_TELEGRAM_API_ID"
    API_HASH="YOUR_TELEGRAM_API_HASH"
    OPENROUTER_API_KEY="sk-or-v1-YOUR_OPENROUTER_API_KEY"
    ```

4.  **Configure Channels**: Open the `channels.json` file. Replace the example content with the source and destination channels you want to use.
    ```json
    {
      "source_channel_username_1": "your_destination_channel_1",
      "source_channel_username_2": "your_destination_channel_2"
    }
    ```

***

## Running the Bot

### Using the .bat Scripts (Windows)

This project includes convenient scripts for running the bot on Windows:

* `start_debug.bat`: Runs the bot in a visible console window. You will see all real-time logs and outputs, which is useful for setup and troubleshooting.
* `start_background.bat`: Runs the bot silently in the background. The console window will not be visible.
* `stop.bat`: Immediately stops the background process started by `start_background.bat`.

### First-Time Run & Telegram Login

**Before you start the bot**, make sure you have filled in your API keys and channel mappings correctly.

For the very first run, it is highly recommended to use `start_debug.bat`. The script needs to log into your Telegram account, and it will prompt you for your information in the console window.

1.  Double-click `start_debug.bat`.
2.  The program will ask for your **phone number**.
3.  Next, it will ask for your **password** (if you have 2-Factor Authentication enabled).
4.  Finally, it will ask for a **login code** that Telegram sends to your app.

This is a **one-time process** required by the Telethon library to create a `.session` file. This file securely saves your login session, so you won't need to log in again.

### Important: Which Telegram Account to Use

It is **highly recommended to use a secondary Telegram account** for this bot, not your main personal account.

There is a small chance that logging in via a script could cause Telegram to log you out of your account on your other devices (phone, desktop app, etc.). This can happen if your account is already logged into many sessions.

You can try using your main account, but if you notice it logs you out elsewhere, you should use a secondary account to avoid this inconvenience.

### Autostart on Windows Startup

To have the bot start automatically when your computer turns on, you can place a shortcut to `start_background.bat` in the Windows Startup folder.

1.  Right-click on `start_background.bat` and select `Create shortcut`.
2.  Press `Win + R` to open the Run dialog.
3.  Type `shell:startup` and press Enter. This will open the Startup folder.
4.  Move the newly created shortcut into this folder.

***

## Configuration

### API Keys (`.env`)
The `.env` file is used to store all your secret credentials. 

### Channel Mappings (`channels.json`)
The `channels.json` file defines the core logic of the bot.
-   The **key** (left side) is the public username of the source channel you want to translate from.
-   The **value** (right side) is the username of the destination channel where the translated post will be sent.

### Customizing the Translation
This bot can be used to translate from **any language to any other language**. To change the translation behavior, you need to edit the `PROMPT_TEMPLATE` variable inside `main.py`.

The current prompt is configured for Russian/English to Japanese translation suitable for an N3-level learner.
```python
# Inside main.py
PROMPT_TEMPLATE = (
    "You are an expert translator, converting text for a Telegram channel into natural-sounding Japanese (JLPT N3 level)..."
)
```
Simply modify the text inside this variable to instruct the AI model to perform the translation you desire (e.g., "Translate the following text from German to Spanish").

### Personal Preferences
The code contains a few personal filtering rules that you may want to keep or remove.

1.  **Ad Filtering**: The bot will skip any posts containing keywords like "реклама" (advertisement). If you want to translate ads, you can comment out or remove this section in the `process_post` function:
    ```python
    # To disable ad filtering, comment out these lines in main.py
    ad_keywords = ["#реклама", "Реклама.", "#промо"]
    if any(keyword in caption_text for keyword in ad_keywords):
        # ... function returns here
    ```

2.  **Channel-Specific Link Stripping**: For the channel `black_triangle_tg`, the code is set to remove all links because their formatting was problematic. If you wish to disable this, comment out or remove this block in the `process_post` function:
    ```python
    # To disable link stripping for this specific channel, comment out these lines
    if source_channel == "black_triangle_tg":
        caption_text = re.sub(r'\s*\([^)]*https?://[^)]+\)', '', caption_text).strip()
    ```

***

## LLM & Cost Recommendations

This project uses the **OpenRouter API**, which gives you access to a wide variety of models at different price points.

For the task of simple text translation, you do not need the most powerful and expensive models. The current configuration uses `google/gemma-3-27b-it`.

Based on my personal usage, running this bot **24/7 monitoring 6 active channels costs approximately $0.005 per day(around 50 to 60 API requests per day), which works out to less than $2 per year**. This makes it an extremely budget-friendly solution.

If you find the translation quality is not sufficient for your needs, you can easily switch to a more powerful model (like GPT-4o or Claude 3 Opus) by changing the `OPENROUTER_MODEL` variable in `main.py`. However, in my experience translating news and articles from English/Russian to Japanese, Gemma-3 is perfectly adequate.

***

## Future Plans & Known Issues

This is a personal project with room for improvement. Here are some thoughts for the future and current limitations.

* **Known Issues**:
    * The main weakness of this project is correctly formatting **embedded links**. Depending on how a source channel formats its posts, links in the translated text can sometimes appear broken or as plain text. The script includes logic to fix the most common formats, but it is not perfect across all channels.

***

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
