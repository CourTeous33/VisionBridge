#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blind_crawler.py

A general crawler framework for extracting content in a blind-friendly manner:
1. Use Selenium for rendering pages and simulating clicks
2. Use OpenAI LLM to extract key content and suggest clickable options
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
    def __init__(self, start_url, api_key, headless=True):
        self.start_url = start_url
        self.tts_engine = pyttsx3.init()

        # Selenium browser setup
        options = Options()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        self.driver = webdriver.Chrome(options=options)

        # OpenAI client
        self.client = OpenAI(api_key=api_key)

        # Interactive controls
        self.interactive = False
        self.clickable_items = []
        self.global_listener = keyboard.Listener(on_press=self._on_press_global)
        self.global_listener.daemon = True
        self.global_listener.start()

    def fetch_dynamic(self, url, click_selector=None):
        self.driver.get(url)
        # Wait for article to load
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "article"))
            )
        except:
            pass
        if click_selector:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, click_selector)
                el.click()
                time.sleep(1)
            except:
                pass
        # Scroll to load lazy content
        try:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        except:
            pass
        # Return only article HTML if possible
        try:
            article = self.driver.find_element(By.TAG_NAME, "article")
            return article.get_attribute("outerHTML")
        except:
            return self.driver.page_source

    def analyze_with_llm(self, html):
        prompt = (
            "You are an intelligent assistant helping visually impaired users navigate web content.\n"
            "1. Based on the HTML content below, extract the main topic and key information, and provide a concise summary.\n"
            "2. If further clicks are needed to reveal more content, return 'click_selector': CSS selector; otherwise, return empty string.\n\n"
            f"--- HTML START ---\n{html}\n--- HTML END ---\n\n"
            "Output JSON: {\"summary\": \"...\", \"click_selector\": \"...\"}"
        )
        resp = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":prompt}],
            temperature=0.2
        )
        try:
            return _json.loads(resp.choices[0].message.content.strip())
        except:
            return {"summary": resp.choices[0].message.content, "click_selector": ""}

    def speak(self, text):
        try:
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except:
            pass

    def announce_clickables(self):
        try:
            elements = self.driver.find_elements(By.CSS_SELECTOR, "a, button")
            self.clickable_items = [el for el in elements if el.text.strip()][:5]
            if self.clickable_items:
                options = [f"Option {i+1}: {el.text.strip()}" for i, el in enumerate(self.clickable_items)]
                speech_text = (
                    "The following clickable items are available. "
                    + ". ".join(options)
                    + ". To click an item, say its number. To exit, say exit."
                    + " Press the spacebar at any time to repeat these options."
                )
            else:
                speech_text = (
                    "No clickable items detected on this page. To exit, say exit."
                    + " Press the spacebar at any time to repeat these options."
                )
            self.speak(speech_text)
        except:
            pass

    def _on_press_global(self, key):
        try:
            if self.interactive and key == keyboard.Key.space:
                self.announce_clickables()
        except:
            pass

    def crawl(self):
        # Initial visit
        url = self.start_url
        parsed = urlparse(url)
        domain = parsed.netloc
        print(f"Visiting: {url}")
        self.speak(f"I am currently visiting {domain}, please wait")

        # Load and analyze
        html = self.fetch_dynamic(url)
        result = self.analyze_with_llm(html)
        summary = result.get("summary", "")
        selector = result.get("click_selector", "").strip()
        if selector:
            html = self.fetch_dynamic(url, selector)
            res2 = self.analyze_with_llm(html)
            summary = res2.get("summary", summary)

        # Clean summary JSON/code fences
        raw = summary.strip()
        if raw.startswith("```"):
            start = raw.find('{'); end = raw.rfind('}')
            if start!=-1 and end>start:
                raw = raw[start:end+1]
        try:
            data = _json.loads(raw)
            summary = data.get("summary", raw)
        except:
            summary = raw

        # Truncate to two sentences
        parts = summary.split('. ')
        if len(parts)>2:
            summary = '. '.join(parts[:2]).strip()
            if not summary.endswith('.'):
                summary += '.'

        print("→ Summary:", summary)
        self.speak(summary)

        # Interactive
        self.announce_clickables()
        self.interactive = True
        while True:
            choice = input("Enter option number (or 'exit'): ").strip()
            if choice.lower() in ('exit','quit'):
                break
            if choice.isdigit():
                idx = int(choice)-1
                if 0<=idx<len(self.clickable_items):
                    element = self.clickable_items[idx]
                else:
                    self.speak("Invalid option number.")
                    continue
            else:
                self.speak("Please enter a valid number.")
                continue

            # Click and update
            try:
                self.driver.execute_script("arguments[0].scrollIntoView(true);", element)
                time.sleep(0.5)
                try: element.click()
                except: self.driver.execute_script("arguments[0].click();", element)
                WebDriverWait(self.driver,10).until(
                    EC.presence_of_element_located((By.TAG_NAME,"article"))
                )
                self.driver.execute_script("window.scrollTo(0,document.body.scrollHeight);")
                time.sleep(2)
                try:
                    art = self.driver.find_element(By.TAG_NAME,"article")
                    html = art.get_attribute("outerHTML")
                except:
                    html = self.driver.page_source
                url = self.driver.current_url
                parsed = urlparse(url)
                domain = parsed.netloc
                # Announce user selection and navigation
                selection_text = element.text.strip()
                self.speak(f"You have selected {selection_text}, now visiting {domain} page, please wait")
            except Exception as e:
                print(f"[Interaction Error] {e}")
                continue

            # Re-analyze
            res = self.analyze_with_llm(html)
            summary = res.get("summary","")
            raw = summary.strip()
            if raw.startswith("```"):
                start = raw.find('{'); end = raw.rfind('}')
                if start!=-1 and end>start:
                    raw = raw[start:end+1]
            try:
                data = _json.loads(raw)
                summary = data.get("summary", raw)
            except:
                summary = raw
            parts = summary.split('. ')
            if len(parts)>2:
                summary = '. '.join(parts[:2]).strip()
                if not summary.endswith('.'):
                    summary += '.'

            print("→ Summary:", summary)
            self.speak(summary)
            self.announce_clickables()

        self.interactive = False
        self.global_listener.stop()
        self.driver.quit()
        print("Crawling completed.")

if __name__ == "__main__":
    import os
    OPENAI_KEY = os.getenv("OPENAI_API_KEY")
    START_URL = "https://www.google.com/"
    crawler = BlindCrawler(start_url=START_URL, api_key=OPENAI_KEY, headless=False)
    crawler.crawl()
