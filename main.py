#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blind_crawler.py

A general crawler framework for extracting content in a blind-friendly manner:
1. Use requests + BeautifulSoup for static pages
2. Use Selenium for simulating clicks and executing JavaScript
3. Use OpenAI LLM to extract key content and suggest click selectors
"""

import time
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium import webdriver

from openai import OpenAI
import pyttsx3
import json as _json
from urllib.parse import urlparse
from pynput import keyboard

class BlindCrawler:
    def __init__(self, start_url, api_key,
                 max_pages=50, delay=1.0,
                 headless=True):
        self.start_url = start_url
        self.domain = None


        # Initialize Selenium WebDriver
        options = Options()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        self.driver = webdriver.Chrome(options=options)

        # Initialize text-to-speech engine
        self.tts_engine = pyttsx3.init()

        # Initialize OpenAI client
        self.client = OpenAI(api_key=api_key)

        # Setup global listener for spacebar to re-announce clickables
        self.interactive = False
        self.global_listener = keyboard.Listener(on_press=self._on_press_global)
        self.global_listener.daemon = True
        self.global_listener.start()

    def fetch_dynamic(self, url, click_selector=None):
        """Load and render page with Selenium and simulate clicks if necessary"""
        self.driver.get(url)
        # Wait for main article content to load
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "article"))
            )
        except Exception:
            pass
        if click_selector:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, click_selector)
                btn.click()
                time.sleep(1)
            except Exception:
                pass
        # Scroll to bottom to load any lazy-loaded content
        try:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        except Exception:
            pass
        # Attempt to extract only the main article content to limit context size
        try:
            article_element = self.driver.find_element(By.TAG_NAME, "article")
            return article_element.get_attribute("outerHTML")
        except Exception:
            return self.driver.page_source

    def analyze_with_llm(self, html):
        """
        Call ChatGPT:
         - Extract the main points of the page most relevant to blind users
         - Return a concise summary and an optional CSS selector for suggested clicks
        """
        prompt = (
            "You are an intelligent assistant helping visually impaired users navigate web content.\n"
            "1. Based on the HTML content below, extract the main topic and key information, and provide a concise summary.\n"
            "2. If further clicks are needed to reveal more content, provide a CSS selector; otherwise, return an empty string.\n\n"
            f"--- HTML START ---\n{html}\n--- HTML END ---\n\n"
            "Please output in JSON format:\n"
            '{"summary": "...", "click_selector": "..."}'
        )
        resp = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        try:
            return _json.loads(resp.choices[0].message.content.strip())
        except Exception:
            # On parsing error, return the full text instead
            return {"summary": resp.choices[0].message.content, "click_selector": ""}

    def crawl(self):
        """Fetch, analyze, and speak a single page specified by start_url using only Selenium."""
        url = self.start_url
        # Extract domain to read only the host part
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        print(f"Visiting: {url}")
        # Announce the start of visiting
        try:
            self.tts_engine.say(f"I am currently visiting {domain}, please wait")
            self.tts_engine.runAndWait()
        except Exception as e:
            print(f"[TTS Error] {e}")
        # Initial page load with Selenium
        try:
            html = self.fetch_dynamic(url)
        except Exception:
            html = ""
        # LLM analysis
        result = self.analyze_with_llm(html)
        summary = result.get("summary", "")
        selector = result.get("click_selector", "").strip()
        # If there's a click selector, reload and re-analyze
        if selector:
            try:
                html = self.fetch_dynamic(url, selector)
                result2 = self.analyze_with_llm(html)
                summary = result2.get("summary", summary)
            except Exception:
                pass

        # Normalize summary: extract actual summary text if JSON or fenced code
        if isinstance(summary, str):
            raw = summary.strip()
            # Remove fenced code blocks and language tags
            if raw.startswith("```"):
                start = raw.find('{')
                end = raw.rfind('}')
                if start != -1 and end != -1 and end > start:
                    raw = raw[start:end+1]
            # Try to parse JSON object to get the inner "summary" field
            try:
                data = _json.loads(raw)
                summary = data.get("summary", raw)
            except Exception:
                # If not valid JSON, use the cleaned raw text
                summary = raw

        print("→ Summary:", summary, "\n")
        try:
            self.tts_engine.say(summary)
            self.tts_engine.runAndWait()
        except Exception as e:
            print(f"[TTS Error] {e}")

        # Announce clickable items and enable interactive re-announcement
        self.announce_clickables()
        self.interactive = True

        # Enter interactive loop for user-driven clicks
        while True:
            choice = input("Enter CSS selector to click (or 'exit' to quit): ").strip()
            if choice.lower() in ('exit', 'quit'):
                break
            # Perform click and re-analyze
            try:
                html = self.fetch_dynamic(url, choice)
                result2 = self.analyze_with_llm(html)
                summary = result2.get("summary", "")
                # Normalize summary JSON/code if needed
                if isinstance(summary, str):
                    raw = summary.strip()
                    if raw.startswith("```"):
                        start = raw.find('{')
                        end = raw.rfind('}')
                        if start != -1 and end != -1 and end > start:
                            raw = raw[start:end+1]
                    try:
                        data = _json.loads(raw)
                        summary = data.get("summary", raw)
                    except Exception:
                        summary = raw
                print("→ Summary:", summary, "\n")
                self.tts_engine.say(summary)
                self.tts_engine.runAndWait()
            except Exception as e:
                print(f"[Interaction Error] {e}")

        # Exit interactive mode and stop listener
        self.interactive = False
        self.global_listener.stop()

        # Clean up after user exits
        self.driver.quit()
        print("Crawling completed.")

    def _on_press_global(self, key):
        # If in interactive mode and space pressed, re-announce clickables
        try:
            if self.interactive and key == keyboard.Key.space:
                self.announce_clickables()
        except Exception:
            pass

    def announce_clickables(self):
        """Speak the available clickable items and instructions."""
        try:
            items = self.driver.find_elements(By.CSS_SELECTOR, "a, button")
            texts = [item.text for item in items if item.text.strip()]
            if texts:
                item_list = ", ".join(texts[:5])
                speech_text = f"The following clickable items are available: {item_list}. To click an item, please enter its CSS selector. To exit, press escape or type exit."
            else:
                speech_text = "No clickable items detected on this page. To exit, press escape or type exit."
            self.speak(speech_text)
        except Exception as e:
            print(f"[TTS Error] {e}")

    def speak(self, text):
        try:
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except Exception as e:
            print(f"[TTS Error] {e}")

if __name__ == "__main__":
    import os
    # Read API key from environment variable (or set it directly here)
    OPENAI_KEY = os.getenv("OPENAI_API_KEY")
    START_URL   = "https://edition.cnn.com/travel/hagia-sophia-istanbul-hidden-history/index.html"
    crawler = BlindCrawler(
        start_url=START_URL,
        api_key=OPENAI_KEY,
        max_pages=30,
        delay=1.5,
        headless=True
    )
    crawler.crawl()
