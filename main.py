#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blind_crawler.py

A general crawler framework for extracting content in a blind-friendly manner:
1. Use Selenium for rendering pages and simulating clicks
2. Use OpenAI LLM to extract key content and suggest clickable options
"""

import time
import os
import platform
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

from selenium import webdriver

from openai import OpenAI
import pyttsx3
import json as _json
from urllib.parse import urlparse
from pynput import keyboard

class BlindCrawler:
    def __init__(self, start_url, api_key, headless=True):
        self.start_url = start_url
        
        # Initialize TTS engine
        try:
            self.tts_engine = pyttsx3.init()
        except Exception as e:
            print(f"Warning: Could not initialize pyttsx3 ({e}). Using system commands for TTS.")
            self.tts_engine = None

        # Selenium browser setup
        options = Options()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        self.driver = webdriver.Chrome(options=options)

        # OpenAI client
        self.client = OpenAI(api_key=api_key)

        # Interactive controls
        self.interactive = False
        self.clickable_items = []
        self.global_listener = keyboard.Listener(on_press=self._on_press_global)
        self.global_listener.daemon = True
        self.global_listener.start()

    def speak(self, text):
        """Enhanced text-to-speech function with fallback mechanisms"""
        if not text or not text.strip():
            print("Warning: Empty text provided to speak function")
            return
            
        print("Speaking:", text[:50] + "..." if len(text) > 50 else text)
        
        # Try pyttsx3 first
        if self.tts_engine is not None:
            try:
                self.tts_engine.say(text)
                self.tts_engine.runAndWait()
                return
            except Exception as e:
                print(f"[pyttsx3 Error] {e}")
                # Try to reinitialize engine
                try:
                    self.tts_engine = pyttsx3.init()
                    self.tts_engine.say(text)
                    self.tts_engine.runAndWait()
                    return
                except Exception as e2:
                    print(f"[pyttsx3 Reinit Error] {e2}")
                    # If reinitialization fails, set to None to use system commands
                    self.tts_engine = None
        
        # Fallback to system commands
        try:
            system = platform.system().lower()
            if system == 'darwin':  # macOS
                # Escape double quotes in text
                escaped_text = text.replace('"', '\\"')
                os.system(f'say "{escaped_text}"')
            elif system == 'linux':
                escaped_text = text.replace('"', '\\"')
                os.system(f'espeak "{escaped_text}"')
            elif system == 'windows':
                import subprocess
                ps_script = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{text.replace("'", "''")}')"
                subprocess.run(["powershell", "-Command", ps_script])
            print("Used system TTS command")
        except Exception as e:
            print(f"[System TTS Error] {e}")
            print("Text was not spoken. Check your TTS configuration.")

    def fetch_dynamic(self, url, click_selector=None):
        """Fetch dynamic page content with special handling for Google and similar sites"""
        try:
            print(f"Fetching URL: {url}")
            if self.driver.current_url != url:
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
            else:
                print("Already on requested URL, refreshing content view")
            
            # Allow more time for JavaScript-heavy sites to initialize
            time.sleep(3)
            
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
                    # Wait for dynamic content to load after click
                    time.sleep(2)
                except Exception as e:
                    print(f"Click selector error: {e}")
                
            # For Google homepage specifically, or when body seems empty
            is_google = "google.com" in url.lower()
            
            # Check if normal extraction would yield empty results
            body_text_length = self.driver.execute_script("return document.body.innerText.length")
            print(f"Body text length: {body_text_length}")
            
            if is_google or body_text_length < 100:
                print("Using special extraction for Google or minimal content page")
                try:
                    # Direct extraction of all visible text and links
                    special_extraction = self.driver.execute_script("""
                        // Get all visible text
                        function getVisibleText(element) {
                            let text = '';
                            
                            // Process this element's direct text if it's visible
                            const style = window.getComputedStyle(element);
                            if (element.offsetWidth && element.offsetHeight && 
                                style.display !== 'none' && style.visibility !== 'hidden') {
                                
                                // Get direct text of this element (not children)
                                for (const node of element.childNodes) {
                                    if (node.nodeType === Node.TEXT_NODE) {
                                        const trimmed = node.textContent.trim();
                                        if (trimmed) text += trimmed + ' ';
                                    }
                                }
                            }
                            
                            // Process children
                            for (const child of element.children) {
                                text += getVisibleText(child) + ' ';
                            }
                            
                            return text;
                        }
                        
                        // Get all visible links
                        function getVisibleLinks() {
                            const links = [];
                            document.querySelectorAll('a').forEach(a => {
                                const style = window.getComputedStyle(a);
                                if (a.offsetWidth && a.offsetHeight && 
                                    style.display !== 'none' && style.visibility !== 'hidden') {
                                    
                                    const text = a.innerText.trim();
                                    const href = a.getAttribute('href');
                                    
                                    if (text && href) {
                                        links.push({ text, href });
                                    }
                                }
                            });
                            return links;
                        }
                        
                        // Get visible buttons
                        function getVisibleButtons() {
                            const buttons = [];
                            document.querySelectorAll('button, [role="button"]').forEach(b => {
                                const style = window.getComputedStyle(b);
                                if (b.offsetWidth && b.offsetHeight && 
                                    style.display !== 'none' && style.visibility !== 'hidden') {
                                    
                                    const text = b.innerText.trim();
                                    if (text) {
                                        buttons.push(text);
                                    }
                                }
                            });
                            return buttons;
                        }
                        
                        // Get any visible input fields
                        function getVisibleInputs() {
                            const inputs = [];
                            document.querySelectorAll('input:not([type="hidden"]), textarea').forEach(input => {
                                const style = window.getComputedStyle(input);
                                if (input.offsetWidth && input.offsetHeight && 
                                    style.display !== 'none' && style.visibility !== 'hidden') {
                                    
                                    const type = input.getAttribute('type') || 'text';
                                    const placeholder = input.getAttribute('placeholder') || '';
                                    const label = input.getAttribute('aria-label') || '';
                                    
                                    inputs.push({ type, placeholder, label });
                                }
                            });
                            return inputs;
                        }
                        
                        // Build a structured representation of the page
                        return {
                            title: document.title,
                            url: window.location.href,
                            visibleText: getVisibleText(document.body),
                            links: getVisibleLinks(),
                            buttons: getVisibleButtons(),
                            inputs: getVisibleInputs()
                        };
                    """)
                    
                    # Convert the JS result to an HTML representation
                    structured_html = f"""
                    <html>
                    <head>
                        <title>{special_extraction['title']}</title>
                    </head>
                    <body>
                        <h1>{special_extraction['title']}</h1>
                        <p>URL: {special_extraction['url']}</p>
                        
                        <h2>Page Text:</h2>
                        <p>{special_extraction['visibleText']}</p>
                        
                        <h2>Links:</h2>
                        <ul>
                            {"".join([f'<li><a href="{link["href"]}">{link["text"]}</a></li>' for link in special_extraction['links']])}
                        </ul>
                        
                        <h2>Buttons:</h2>
                        <ul>
                            {"".join([f'<li>{button}</li>' for button in special_extraction['buttons']])}
                        </ul>
                        
                        <h2>Input Fields:</h2>
                        <ul>
                            {"".join([f'<li>Type: {inp["type"]}, Placeholder: {inp["placeholder"]}, Label: {inp["label"]}</li>' for inp in special_extraction['inputs']])}
                        </ul>
                    </body>
                    </html>
                    """
                    
                    print(f"Generated structured HTML representation, length: {len(structured_html)}")
                    return structured_html
                except Exception as e:
                    print(f"Special extraction error: {e}")
                    # Continue to regular extraction methods if this fails
            
            # Try standard content extraction methods
            content_selectors = [
                "article", "main", "#content", ".content", "#main", ".main",
                "section", ".post", ".article", "[role='main']"
            ]
            
            # Try to find main content container
            for selector in content_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        try:
                            html = el.get_attribute("outerHTML")
                            if len(html) > 100:  # Only consider substantial content
                                print(f"Found content with selector: {selector}, length: {len(html)}")
                                return html
                        except:
                            continue
                except:
                    continue
            
            # If no main content found, use full page but clean it
            try:
                # Use JavaScript to extract and clean the visible content
                cleaned_html = self.driver.execute_script("""
                    // Create a clone to work with
                    const clone = document.documentElement.cloneNode(true);
                    
                    // Remove scripts and styles to reduce size
                    const elementsToRemove = clone.querySelectorAll('script, style, link, meta, noscript, iframe');
                    elementsToRemove.forEach(el => el.parentNode.removeChild(el));
                    
                    return clone.outerHTML;
                """)
                
                print(f"Using cleaned full page HTML, length: {len(cleaned_html)}")
                return cleaned_html
            except Exception as e:
                print(f"HTML cleaning error: {e}")
            
            # Absolute last resort: return page source
            return self.driver.page_source
        except Exception as e:
            print(f"[Fetch Error] {e}")
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

    def announce_clickables(self):
        """Get and announce clickable items on the page with pagination support"""
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
                    # Ignore stale element references
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
            
            # Store all clickable items for pagination
            self.all_clickable_items = [(el, identifier) for el, identifier in unique_elements]
            self.current_page = 0
            self.items_per_page = 5
            total_pages = (len(self.all_clickable_items) + self.items_per_page - 1) // self.items_per_page
            
            self._announce_current_page()
            
        except Exception as e:
            print(f"[Announce Clickables Error] {e}")
            self.speak("There was an error identifying clickable elements.")
            # Reset clickable items list
            self.all_clickable_items = []
            self.clickable_items = []

    def _on_press_global(self, key):
        try:
            if self.interactive and key == keyboard.Key.space:
                self.announce_clickables()
        except:
            pass

    def _announce_current_page(self):
        """Announce the current page of clickable items"""
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.all_clickable_items))
        
        # Update current page clickable items
        current_page_items = self.all_clickable_items[start_idx:end_idx]
        self.clickable_items = [el for el, _ in current_page_items]
        
        if not self.clickable_items:
            speech_text = "No clickable items detected on this page. To exit, say exit."
            self.speak(speech_text)
            return
            
        # Create speech prompt
        options = []
        for i, (_, identifier) in enumerate(current_page_items):
            # Limit identifier length to make it easier to understand
            short_id = identifier if len(identifier) < 30 else identifier[:27] + "..."
            options.append(f"Option {i+1}: {short_id}")
        
        # Information about pagination
        total_pages = (len(self.all_clickable_items) + self.items_per_page - 1) // self.items_per_page
        page_info = f"Page {self.current_page + 1} of {total_pages}. "
        
        if total_pages > 1:
            if self.current_page < total_pages - 1:
                page_info += "Press Enter to hear more options. "
        
        speech_text = (
            page_info
            + "The following clickable items are available. "
            + ". ".join(options)
            + ". To click an item, say its number. To exit, say exit."
            + " Press the spacebar at any time to repeat these options."
        )
        
        print(f"Announcing {len(self.clickable_items)} clickable items")
        self.speak(speech_text)

    def crawl(self):
        # Initial visit
        url = self.start_url
        parsed = urlparse(url)
        domain = parsed.netloc[parsed.netloc.find('.') + 1:]
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
            if choice == "":
                # Advance to next page of clickable items
                total_pages = (len(self.all_clickable_items) + self.items_per_page - 1) // self.items_per_page
                if self.current_page < total_pages - 1:
                    self.current_page += 1
                self._announce_current_page()
                continue
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
                
                # Announce the user's selection immediately
                selection_text = element_text or f"option {idx+1}"
                self.speak(f"You selected {selection_text}. Processing, please wait.")
                
                # Take a snapshot of current DOM state before clicking
                pre_click_snapshot = self.driver.execute_script("""
                    return {
                        bodyText: document.body.innerText.substring(0, 1000), 
                        elementCount: document.getElementsByTagName('*').length,
                        height: document.body.scrollHeight,
                        width: document.body.scrollWidth,
                        visibleElements: Array.from(
                            document.querySelectorAll('a, button, [role="button"], input[type="submit"]')
                        ).filter(el => {
                            const rect = el.getBoundingClientRect();
                            return (
                                el.offsetWidth > 0 &&
                                el.offsetHeight > 0 &&
                                rect.top < window.innerHeight &&
                                rect.left < window.innerWidth &&
                                getComputedStyle(el).visibility !== 'hidden' &&
                                getComputedStyle(el).display !== 'none'
                            );
                        }).length
                    }
                """)
                print("Pre-click DOM snapshot captured")
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
                
            # Wait for page changes - improved detection for SPAs
            content_changed = False
            try:
                # First check if new window was created
                window_handles = self.driver.window_handles
                if len(window_handles) > 1:
                    # Switch to the newest window
                    self.driver.switch_to.window(window_handles[-1])
                    print("Switched to new window")
                    content_changed = True
                    time.sleep(3)
                
                # Check if URL changed
                try:
                    url_changed = WebDriverWait(self.driver, 3).until(
                        lambda d: d.current_url != current_url
                    )
                    if url_changed:
                        print("URL changed:", self.driver.current_url)
                        content_changed = True
                        time.sleep(2)
                except:
                    print("URL did not change, checking for DOM changes...")
                    
                    # Initial wait for any AJAX or dynamic content
                    time.sleep(2)
                    
                    # Check for DOM changes when URL didn't change (for SPA detection)
                    max_wait = 10  # Maximum seconds to wait for changes
                    start_time = time.time()
                    
                    while not content_changed and (time.time() - start_time) < max_wait:
                        # Get current DOM snapshot and compare with pre-click
                        post_click_snapshot = self.driver.execute_script("""
                            return {
                                bodyText: document.body.innerText.substring(0, 1000),
                                elementCount: document.getElementsByTagName('*').length,
                                height: document.body.scrollHeight,
                                width: document.body.scrollWidth,
                                visibleElements: Array.from(
                                    document.querySelectorAll('a, button, [role="button"], input[type="submit"]')
                                ).filter(el => {
                                    const rect = el.getBoundingClientRect();
                                    return (
                                        el.offsetWidth > 0 &&
                                        el.offsetHeight > 0 &&
                                        rect.top < window.innerHeight &&
                                        rect.left < window.innerWidth &&
                                        getComputedStyle(el).visibility !== 'hidden' &&
                                        getComputedStyle(el).display !== 'none'
                                    );
                                }).length
                            }
                        """)
                        
                        # Detect various types of changes
                        text_changed = pre_click_snapshot['bodyText'] != post_click_snapshot['bodyText']
                        elements_changed = abs(pre_click_snapshot['elementCount'] - post_click_snapshot['elementCount']) > 5
                        size_changed = (
                            abs(pre_click_snapshot['height'] - post_click_snapshot['height']) > 50 or
                            abs(pre_click_snapshot['width'] - post_click_snapshot['width']) > 50
                        )
                        visible_elements_changed = pre_click_snapshot['visibleElements'] != post_click_snapshot['visibleElements']
                        
                        # Determine if content changed significantly
                        if text_changed or elements_changed or size_changed or visible_elements_changed:
                            print("DOM changes detected:")
                            if text_changed: print("- Text content changed")
                            if elements_changed: print(f"- Element count changed: {pre_click_snapshot['elementCount']} → {post_click_snapshot['elementCount']}")
                            if size_changed: print(f"- Size changed: {pre_click_snapshot['height']}x{pre_click_snapshot['width']} → {post_click_snapshot['height']}x{post_click_snapshot['width']}")
                            if visible_elements_changed: print(f"- Visible interactive elements changed: {pre_click_snapshot['visibleElements']} → {post_click_snapshot['visibleElements']}")
                            
                            content_changed = True
                            break
                        
                        # Try scrolling slightly to trigger lazy loading
                        self.driver.execute_script("window.scrollBy(0, 100);")
                        time.sleep(0.5)
                    
                    if not content_changed:
                        print("No significant DOM changes detected after click")
                        # Even if no changes detected, we'll still proceed to analyze the page
                        # as there might be subtle changes our detection missed
                
                # Get current URL info for announcement
                url = self.driver.current_url
                parsed = urlparse(url)
                domain = parsed.netloc
                # If still on the same page but DOM updated, announce only new content and new clickables
                if content_changed and url == current_url:
                    # Determine newly added text
                    new_text = post_click_snapshot['bodyText'].replace(pre_click_snapshot['bodyText'], '').strip()
                    if new_text:
                        self.speak("New content: " + new_text)
                    # Announce only the new clickable items
                    self.announce_clickables()
                    # Skip full analysis and wait for user selection
                    continue
                # Otherwise, full-analysis path
                if url != current_url:
                    self.speak(f"Page changed to {domain}. Analyzing new content...")
                else:
                    self.speak(f"Still on {domain}. Analyzing current page content...")
                    
            except Exception as e:
                print(f"[Navigation detection error] {e}")
                self.speak("Navigation detection encountered an error. Continuing with analysis.")
            
            # Get and analyze the page content (even if no changes detected)
            try:
                # Fetch the current page content
                content_html = self.fetch_dynamic(self.driver.current_url)
                
                # Analyze with LLM
                res = self.analyze_with_llm(content_html)
                summary = res.get("summary", "")
                
                # Process the summary
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
                
                # Output and speak the summary
                print("→ Summary:", summary)
                self.speak(summary)
                
                # Wait to ensure speech is complete
                time.sleep(1)
            except Exception as e:
                print(f"[Analysis Error] {e}")
                self.speak("There was an error analyzing the page content.")
            
            # Announce new clickable items for this page
            time.sleep(1)  # Give a slight pause
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