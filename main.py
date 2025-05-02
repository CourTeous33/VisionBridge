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
        """Fetch dynamic page content, selectively retrieving only main content"""
        try:
            print(f"Fetching URL: {url}")
            self.driver.get(url)
            # Wait for page to load
            try:
                # Wait for page ready state
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                print("Page loaded (readyState complete)")
            except Exception as e:
                print(f"Wait for page load error: {e}")
                
            # If we need to click an element
            if click_selector:
                print(f"Attempting to click selector: {click_selector}")
                try:
                    # Wait for element to be clickable
                    element = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, click_selector))
                    )
                    # Scroll to element
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.5)
                    # Try to click
                    try:
                        element.click()
                    except:
                        self.driver.execute_script("arguments[0].click();", element)
                    print(f"Clicked element with selector: {click_selector}")
                    # Wait for page to update after click
                    time.sleep(2)
                except Exception as e:
                    print(f"Click selector error: {e}")
                    
            # Perform limited scrolling to avoid loading too much content
            try:
                # Get page height
                total_height = self.driver.execute_script("return document.body.scrollHeight")
                # Moderate scroll, not to the bottom
                self.driver.execute_script(f"window.scrollTo(0, {min(1000, total_height/2)});")
                time.sleep(0.5)
                # Scroll back to top
                self.driver.execute_script("window.scrollTo(0, 0);")
                print("Completed moderate scrolling")
            except Exception as e:
                print(f"Scroll error: {e}")
                
            # Intelligently extract main page content, not the entire page
            # Try various content containers in priority order
            content_selectors = [
                "article", "main", 
                "#content", ".content", "#main", ".main",
                "section", ".post", ".article",
                ".page-content", ".entry-content"
            ]
            
            # Try to find main content container
            for selector in content_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        # Find the most content-rich element (usually the one with most text)
                        max_length = 0
                        best_html = ""
                        for el in elements:
                            html = el.get_attribute("outerHTML")
                            if len(html) > max_length:
                                max_length = len(html)
                                best_html = html
                        
                        if best_html:
                            print(f"Found main content container: {selector}, length: {max_length}")
                            return best_html
                except Exception as e:
                    print(f"Selector {selector} lookup error: {e}")
                    continue
            
            # If no main content container found, try to extract only visible elements from body
            try:
                # Use JavaScript to remove all script, style, meta etc. invisible elements
                cleaned_html = self.driver.execute_script("""
                    var clone = document.body.cloneNode(true);
                    // Remove scripts and styles
                    var elementsToRemove = clone.querySelectorAll('script, style, link, meta, noscript, iframe');
                    elementsToRemove.forEach(function(element) {
                        element.parentNode.removeChild(element);
                    });
                    return clone.outerHTML;
                """)
                print(f"Extracted cleaned body content, length: {len(cleaned_html)}")
                return cleaned_html
            except Exception as e:
                print(f"HTML cleaning error: {e}")
                
            # Last resort: return entire page, but it will be truncated in analyze_with_llm
            print("No main content container found, returning entire page")
            return self.driver.page_source
        except Exception as e:
            print(f"[Fetch Error] {e}")
            # Return current page content, even if it's an error page
            return self.driver.page_source

    def analyze_with_llm(self, html):
        """Use LLM to analyze HTML content while ensuring token limits aren't exceeded"""
        # Limit HTML size to prevent token limit errors
        max_html_length = 60000  # Approximately 30,000 tokens
        
        if len(html) > max_html_length:
            print(f"HTML content too large: {len(html)} chars, truncating...")
            # Keep first 2/3 and last 1/3 of content
            head_size = max_html_length * 2 // 3
            tail_size = max_html_length - head_size
            truncated_html = html[:head_size] + "\n...[CONTENT TRUNCATED]...\n" + html[-tail_size:]
            html = truncated_html
            print(f"Truncated HTML size: {len(html)} chars")
        
        prompt = (
            "You are an intelligent assistant helping visually impaired users navigate web content.\n"
            "1. Based on the HTML content below, extract the main topic and key information, and provide a concise summary.\n"
            "2. If further clicks are needed to reveal more content, return 'click_selector': CSS selector; otherwise, return empty string.\n\n"
            f"--- HTML START ---\n{html}\n--- HTML END ---\n\n"
            "Output JSON: {\"summary\": \"...\", \"click_selector\": \"...\"}"
        )
        
        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role":"user","content":prompt}],
                temperature=0.2,
                max_tokens=500  # Limit response length
            )
            try:
                return _json.loads(resp.choices[0].message.content.strip())
            except:
                return {"summary": resp.choices[0].message.content, "click_selector": ""}
        except Exception as e:
            print(f"[LLM API Error] {e}")
            # Handle token limit errors
            if "context_length_exceeded" in str(e) or "maximum context length" in str(e):
                print("Token limit error, further reducing HTML size...")
                # Reduce HTML size by half and retry
                if len(html) > 30000:
                    html = html[:15000] + "\n...[CONTENT HEAVILY TRUNCATED]...\n" + html[-15000:]
                    print(f"Heavily truncated HTML size: {len(html)} chars")
                    return self.analyze_with_llm(html)  # Recursive call
                else:
                    # HTML is already small but still exceeds limits
                    return {
                        "summary": "Web content too large to analyze. This may be a complex page.",
                        "click_selector": ""
                    }
            # Other API errors
            return {
                "summary": "Error occurred while analyzing the page. Please try another action.",
                "click_selector": ""
            }

    def speak(self, text):
        try:
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except:
            pass

    def announce_clickables(self):
        """Get and announce clickable items on the page, more robust implementation"""
        try:
            # Ensure page has stabilized
            time.sleep(1)
            
            # Broader selectors to find various interactive elements
            selectors = [
                "a[href]:not([href='#']):not([aria-hidden='true'])", 
                "button:not([aria-hidden='true'])",
                "[role='button']",
                "input[type='submit']",
                ".btn", 
                "[onclick]",
                "[tabindex='0']"
            ]
            
            # Use combined selector to find all elements at once
            combined_selector = ", ".join(selectors)
            print(f"Searching for elements with selector: {combined_selector}")
            
            try:
                # Wait for at least one element to be visible
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, combined_selector))
                )
            except Exception as e:
                print(f"Waiting for elements failed: {e}")
            
            # Find all potential clickable elements
            all_elements = []
            try:
                all_elements = self.driver.find_elements(By.CSS_SELECTOR, combined_selector)
                print(f"Found {len(all_elements)} potential clickable elements")
            except Exception as e:
                print(f"Finding elements failed: {e}")
                
            # Filter out invisible or no-text elements
            visible_elements = []
            for el in all_elements:
                try:
                    if el.is_displayed():
                        # Get element's text and other identifying attributes
                        el_text = el.text.strip()
                        el_aria = el.get_attribute("aria-label")
                        el_title = el.get_attribute("title")
                        el_value = el.get_attribute("value")
                        
                        # Use any available identifier
                        identifier = el_text or el_aria or el_title or el_value
                        
                        if identifier:
                            visible_elements.append((el, identifier))
                except Exception as e:
                    # Ignore stale element errors
                    if "stale element reference" not in str(e).lower():
                        print(f"Element visibility check error: {e}")
                    continue
                    
            print(f"Filtered to {len(visible_elements)} visible elements with text")
            
            # Deduplicate (based on identifier)
            seen_ids = set()
            unique_elements = []
            for el, identifier in visible_elements:
                # Use first 30 chars as unique identifier
                short_id = identifier[:30].lower()
                if short_id not in seen_ids:
                    seen_ids.add(short_id)
                    unique_elements.append((el, identifier))
                    
            print(f"Deduplicated to {len(unique_elements)} unique elements")
            
            # Keep at most 5 elements
            self.clickable_items = [el for el, _ in unique_elements[:5]]
            
            if self.clickable_items:
                # Create speech prompt
                options = []
                for i, (el, identifier) in enumerate(unique_elements[:5]):
                    # Limit identifier length to make it easier to understand
                    short_id = identifier if len(identifier) < 30 else identifier[:27] + "..."
                    options.append(f"Option {i+1}: {short_id}")
                
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
            
            print(f"Announcing {len(self.clickable_items)} clickable items")
            self.speak(speech_text)
        except Exception as e:
            print(f"[Announce Clickables Error] {e}")
            self.speak("There was an error identifying clickable elements.")
            # Reset clickable items list
            self.clickable_items = []

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
                
            if not choice.isdigit():
                self.speak("Please enter a valid number.")
                continue
                
            idx = int(choice)-1
            if idx < 0 or idx >= len(self.clickable_items):
                self.speak("Invalid option number.")
                continue
                
            # Save information about the element to click, not the element itself
            # This way, even if the element becomes stale, we can try to relocate it
            try:
                click_item = self.clickable_items[idx]
                element_text = click_item.text.strip()
                element_tag = click_item.tag_name
                element_href = click_item.get_attribute("href") if element_tag == "a" else None
                element_xpath = self.driver.execute_script("""
                    function getElementXPath(element) {
                        if (element && element.id)
                            return '//*[@id="' + element.id + '"]';
                        
                        var paths = [];
                        for (; element && element.nodeType == 1; element = element.parentNode) {
                            var index = 0;
                            for (var sibling = element.previousSibling; sibling; sibling = sibling.previousSibling) {
                                if (sibling.nodeType == Node.DOCUMENT_TYPE_NODE)
                                    continue;
                                if (sibling.nodeName == element.nodeName)
                                    ++index;
                            }
                            var tagName = element.nodeName.toLowerCase();
                            var pathIndex = (index ? "[" + (index+1) + "]" : "");
                            paths.unshift(tagName + pathIndex);
                        }
                        return "/" + paths.join("/");
                    }
                    return getElementXPath(arguments[0]);
                """, click_item)
            except Exception as e:
                print(f"Error saving element info: {e}")
                self.speak("Could not find the selected element.")
                self.announce_clickables()  # Refresh clickable items
                continue

            # Record current URL
            current_url = self.driver.current_url
            
            # Try to click the element
            clicked = False
            try:
                # 1. First try direct click on original element
                try:
                    click_item.click()
                    clicked = True
                    print("Clicked element directly")
                except Exception as e1:
                    print(f"Direct click failed: {e1}")
                    
                    # 2. If direct click fails, try JavaScript click
                    try:
                        self.driver.execute_script("arguments[0].click();", click_item)
                        clicked = True
                        print("Clicked element via JavaScript")
                    except Exception as e2:
                        print(f"JS click failed: {e2}")
                        
                        # 3. If element is stale, try to relocate based on saved info
                        try:
                            # Try to find element by text and tag first
                            if element_text:
                                xpath_query = f"//{element_tag}[contains(text(), '{element_text}')]"
                                print(f"Trying to find by XPath: {xpath_query}")
                                new_element = self.driver.find_element(By.XPATH, xpath_query)
                                new_element.click()
                                clicked = True
                                print("Clicked element found by text")
                            # If it's a link with href attribute, try to find by href
                            elif element_href:
                                print(f"Trying to find by href: {element_href}")
                                new_element = self.driver.find_element(By.CSS_SELECTOR, f"a[href='{element_href}']")
                                new_element.click()
                                clicked = True
                                print("Clicked element found by href")
                            # Finally try to find by saved XPath
                            elif element_xpath:
                                print(f"Trying to find by saved XPath: {element_xpath}")
                                new_element = self.driver.find_element(By.XPATH, element_xpath)
                                new_element.click()
                                clicked = True
                                print("Clicked element found by XPath")
                        except Exception as e3:
                            print(f"Element relocation failed: {e3}")
                            
                            # 4. Last resort: try to click new refreshed clickable items list
                            try:
                                # Refresh clickable items list
                                print("Refreshing clickable items list")
                                elements = self.driver.find_elements(By.CSS_SELECTOR, "a, button")
                                visible_elements = [el for el in elements if el.is_displayed() and el.text.strip()]
                                self.clickable_items = visible_elements[:5]
                                
                                if idx < len(self.clickable_items):
                                    print(f"Trying to click refreshed element at index {idx}")
                                    self.clickable_items[idx].click()
                                    clicked = True
                                    print("Clicked element from refreshed list")
                            except Exception as e4:
                                print(f"Refreshed click failed: {e4}")
            except Exception as e:
                print(f"All click attempts failed: {e}")
                
            if not clicked:
                self.speak("Could not click the selected element. Please try another option.")
                # Refresh clickable items
                self.announce_clickables()
                continue
                
            # Wait for page changes - three possibilities:
            # 1. URL changes - standard navigation
            # 2. Page content changes - AJAX or SPA
            # 3. New window/tab opens - need to switch windows
            
            # First check if new window was created
            try:
                # Get all window handles
                window_handles = self.driver.window_handles
                if len(window_handles) > 1:
                    # Switch to the newest window
                    self.driver.switch_to.window(window_handles[-1])
                    print("Switched to new window")
                    # Give new window some time to load
                    time.sleep(3)
            except Exception as e:
                print(f"Window handling error: {e}")
            
            # Check if URL changed
            url_changed = False
            try:
                url_changed = WebDriverWait(self.driver, 3).until(
                    lambda d: d.current_url != current_url
                )
                if url_changed:
                    print("URL changed:", self.driver.current_url)
                    # Give new page time to load
                    time.sleep(2)
            except:
                print("URL did not change")
                # URL didn't change, might be AJAX content update, wait a bit
                time.sleep(3)
            
            # Try to get page HTML - using more robust method
            try:
                # First try to get main content container
                content_html = ""
                for selector in ["article", "main", "#content", ".content", "body"]:
                    try:
                        content = self.driver.find_element(By.CSS_SELECTOR, selector)
                        content_html = content.get_attribute("outerHTML")
                        print(f"Found content with selector: {selector}")
                        break
                    except:
                        continue
                        
                # If no content container found, get entire page source
                if not content_html:
                    content_html = self.driver.page_source
                    print("Using full page source")
                    
                # Get current URL info
                url = self.driver.current_url
                parsed = urlparse(url)
                domain = parsed.netloc
                
                # Announce user selection and navigation
                selection_text = element_text or "selected"
                self.speak(f"You have selected the {selection_text} option, now visiting {domain} page, please wait")
                
                # Short pause
                time.sleep(1)
            except Exception as e:
                print(f"[Content Extraction Error] {e}")
                self.speak("There was an error extracting content from the page.")
                # Try to refresh clickable items
                self.announce_clickables()
                continue

            # Re-analyze
            try:
                res = self.analyze_with_llm(content_html)
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
                
                # Wait to ensure page has fully loaded
                time.sleep(2)
            except Exception as e:
                print(f"[Analysis Error] {e}")
                self.speak("There was an error analyzing the page content.")
            
            # Announce new clickable items for this page
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
