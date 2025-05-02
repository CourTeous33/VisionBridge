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
        try:
            print(f"Fetching URL: {url}")
            self.driver.get(url)
            # 等待页面加载
            try:
                # 等待页面准备就绪
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                print("Page loaded (readyState complete)")
            except Exception as e:
                print(f"Wait for page load error: {e}")
                
            # 等待可见内容出现
            for selector in ["article", "main", "#content", ".content", "body"]:
                try:
                    WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    print(f"Found visible content with selector: {selector}")
                    break
                except:
                    continue
            
            # 如果需要点击某个元素
            if click_selector:
                print(f"Attempting to click selector: {click_selector}")
                try:
                    # 等待元素可点击
                    element = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, click_selector))
                    )
                    # 滚动到元素
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.5)
                    # 尝试点击
                    try:
                        element.click()
                    except:
                        self.driver.execute_script("arguments[0].click();", element)
                    print(f"Clicked element with selector: {click_selector}")
                    # 等待点击后页面变化
                    time.sleep(2)
                except Exception as e:
                    print(f"Click selector error: {e}")
                    
            # 执行渐进式滚动，以加载所有延迟内容
            try:
                # 获取页面高度
                total_height = self.driver.execute_script("return document.body.scrollHeight")
                # 以较小的步幅滚动
                for i in range(3):
                    scroll_height = (i+1) * total_height / 3
                    self.driver.execute_script(f"window.scrollTo(0, {scroll_height});")
                    time.sleep(0.5)
                # 滚动回顶部
                self.driver.execute_script("window.scrollTo(0, 0);")
                print("Completed progressive scrolling")
            except Exception as e:
                print(f"Scroll error: {e}")
                
            # 尝试找到主要内容
            try:
                article = self.driver.find_element(By.TAG_NAME, "article")
                return article.get_attribute("outerHTML")
            except:
                try:
                    main = self.driver.find_element(By.TAG_NAME, "main")
                    return main.get_attribute("outerHTML")
                except:
                    # 如果找不到特定内容容器，返回整个页面
                    return self.driver.page_source
        except Exception as e:
            print(f"[Fetch Error] {e}")
            # 返回当前页面内容，即使是错误页面
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
            # 更多的选择器类型，以找到更多可能的交互元素
            selectors = [
                "a[href]:not([href='#']):not([href='']):not([aria-hidden='true'])", 
                "button:not([disabled]):not([aria-hidden='true'])",
                "[role='button']:not([disabled]):not([aria-hidden='true'])",
                "input[type='submit']:not([disabled])",
                "[tabindex]:not([tabindex='-1']):not(body)"
            ]
            
            # 使用更复杂的选择器来查找元素
            elements = []
            for selector in selectors:
                try:
                    found = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    elements.extend(found)
                except:
                    pass
            
            # 过滤掉不可见或无文本的元素
            visible_elements = []
            for el in elements:
                try:
                    if el.is_displayed() and (el.text.strip() or el.get_attribute("aria-label")):
                        # 使用文本或aria-label作为标识
                        visible_elements.append(el)
                except:
                    continue
            
            # 删除重复元素（基于文本内容）
            unique_text = set()
            unique_elements = []
            for el in visible_elements:
                text = el.text.strip() or el.get_attribute("aria-label") or "Unnamed Element"
                if text and text not in unique_text:
                    unique_text.add(text)
                    unique_elements.append(el)
            
            # 限制数量并保存结果
            self.clickable_items = unique_elements[:5]
            
            if self.clickable_items:
                options = []
                for i, el in enumerate(self.clickable_items):
                    text = el.text.strip() or el.get_attribute("aria-label") or f"Element {i+1}"
                    options.append(f"Option {i+1}: {text}")
                
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
        except Exception as e:
            print(f"[Announce Error] {e}")
            self.speak("There was an error identifying clickable elements.")

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
                
            # 保存要点击的元素的信息，而不是元素本身
            # 这样即使元素变得过时，我们也可以尝试重新定位它
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
                self.announce_clickables()  # 重新获取可点击项
                continue

            # 记录当前URL
            current_url = self.driver.current_url
            
            # 尝试点击元素
            clicked = False
            try:
                # 1. 首先尝试直接点击原始元素
                try:
                    click_item.click()
                    clicked = True
                    print("Clicked element directly")
                except Exception as e1:
                    print(f"Direct click failed: {e1}")
                    
                    # 2. 如果直接点击失败，尝试通过JavaScript点击
                    try:
                        self.driver.execute_script("arguments[0].click();", click_item)
                        clicked = True
                        print("Clicked element via JavaScript")
                    except Exception as e2:
                        print(f"JS click failed: {e2}")
                        
                        # 3. 如果元素过时，尝试根据保存的信息重新定位元素
                        try:
                            # 先尝试通过文本和标签找到元素
                            if element_text:
                                xpath_query = f"//{element_tag}[contains(text(), '{element_text}')]"
                                print(f"Trying to find by XPath: {xpath_query}")
                                new_element = self.driver.find_element(By.XPATH, xpath_query)
                                new_element.click()
                                clicked = True
                                print("Clicked element found by text")
                            # 如果是链接且有href属性，尝试通过href找到
                            elif element_href:
                                print(f"Trying to find by href: {element_href}")
                                new_element = self.driver.find_element(By.CSS_SELECTOR, f"a[href='{element_href}']")
                                new_element.click()
                                clicked = True
                                print("Clicked element found by href")
                            # 最后尝试通过保存的XPath找到元素
                            elif element_xpath:
                                print(f"Trying to find by saved XPath: {element_xpath}")
                                new_element = self.driver.find_element(By.XPATH, element_xpath)
                                new_element.click()
                                clicked = True
                                print("Clicked element found by XPath")
                        except Exception as e3:
                            print(f"Element relocation failed: {e3}")
                            
                            # 4. 最后尝试使用索引点击新获取的可点击项列表
                            try:
                                # 刷新可点击项目列表
                                print("Refreshing clickable items list")
                                elements = self.driver.find_elements(By.CSS_SELECTOR, "a, button")
                                self.clickable_items = [el for el in elements if el.is_displayed() and el.text.strip()][:5]
                                
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
                # 重新获取可点击项
                self.announce_clickables()
                continue
                
            # 等待页面变化 - 有三种可能性:
            # 1. URL改变 - 标准导航
            # 2. 页面内容变化 - AJAX或SPA
            # 3. 新窗口或标签页打开 - 需要切换窗口
            
            # 首先检查是否创建了新窗口
            try:
                # 获取当前所有窗口句柄
                window_handles = self.driver.window_handles
                if len(window_handles) > 1:
                    # 切换到最新的窗口
                    self.driver.switch_to.window(window_handles[-1])
                    print("Switched to new window")
                    # 给新窗口一些加载时间
                    time.sleep(3)
            except Exception as e:
                print(f"Window handling error: {e}")
            
            # 检查URL是否改变
            url_changed = False
            try:
                url_changed = WebDriverWait(self.driver, 3).until(
                    lambda d: d.current_url != current_url
                )
                if url_changed:
                    print("URL changed:", self.driver.current_url)
                    # 给新页面时间加载
                    time.sleep(2)
            except:
                print("URL did not change")
                # URL没有改变，可能是AJAX内容更新，等待一会儿
                time.sleep(3)
            
            # 尝试获取页面HTML - 使用更健壮的方法
            try:
                # 首先尝试获取主要内容容器
                content_html = ""
                for selector in ["article", "main", "#content", ".content", "body"]:
                    try:
                        content = self.driver.find_element(By.CSS_SELECTOR, selector)
                        content_html = content.get_attribute("outerHTML")
                        print(f"Found content with selector: {selector}")
                        break
                    except:
                        continue
                        
                # 如果没有找到任何内容容器，获取整个页面源代码
                if not content_html:
                    content_html = self.driver.page_source
                    print("Using full page source")
                    
                # 获取当前URL信息
                url = self.driver.current_url
                parsed = urlparse(url)
                domain = parsed.netloc
                
                # 宣布用户选择和导航
                selection_text = element_text or "selected"
                self.speak(f"You have selected the {selection_text} option, now visiting {domain} page, please wait")
                
                # 短暂停顿
                time.sleep(1)
            except Exception as e:
                print(f"[Content Extraction Error] {e}")
                self.speak("There was an error extracting content from the page.")
                # 尝试重新获取可点击项目
                self.announce_clickables()
                continue

            # 重新分析
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
                
                # 等待确保页面已经完全加载
                time.sleep(2)
            except Exception as e:
                print(f"[Analysis Error] {e}")
                self.speak("There was an error analyzing the page content.")
            
            # 宣布此页面的新可点击项目
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
