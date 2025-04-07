import requests
from bs4 import BeautifulSoup
import re
from typing import Dict, List, Tuple
import openai

class WebsiteAccessibilityAgent:
    def __init__(self, api_key: str):
        """Initialize the agent with the OpenAI API key."""
        self.api_key = api_key
        openai.api_key = api_key
        
    def fetch_webpage(self, url: str) -> str:
        """Fetch the HTML content of a webpage."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Error fetching webpage: {e}")
            return ""
    
    def preprocess_html(self, html_content: str) -> BeautifulSoup:
        """Parse and preprocess the HTML content."""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.extract()
            
        return soup
    
    def extract_main_content(self, soup: BeautifulSoup) -> str:
        """Extract the main content from the webpage."""
        # Try to find main content containers
        main_tags = soup.find_all(['main', 'article', 'div', 'section'], 
                                 class_=re.compile(r'(content|main|article)'))
        
        if main_tags:
            # Use the largest content block as the main content
            main_content = max(main_tags, key=lambda x: len(x.get_text()))
            return main_content.get_text(strip=True)
        
        # Fallback: use body content
        return soup.body.get_text(strip=True)
    
    def extract_interactive_elements(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract interactive elements like buttons, links, and forms."""
        interactive_elements = []
        
        # Extract links
        for link in soup.find_all('a', href=True):
            text = link.get_text(strip=True)
            if text:
                interactive_elements.append({
                    'type': 'link',
                    'text': text,
                    'href': link['href']
                })
        
        # Extract buttons
        for button in soup.find_all(['button', 'input']):
            if button.name == 'input' and button.get('type') not in ['submit', 'button', 'reset']:
                continue
                
            text = button.get_text(strip=True) or button.get('value', '') or button.get('aria-label', '')
            if text:
                interactive_elements.append({
                    'type': 'button',
                    'text': text
                })
        
        # Extract forms
        for form in soup.find_all('form'):
            form_elements = []
            for input_field in form.find_all(['input', 'textarea', 'select']):
                field_type = input_field.get('type', input_field.name)
                label_text = ""
                
                # Try to find label
                if input_field.get('id'):
                    label = soup.find('label', attrs={'for': input_field['id']})
                    if label:
                        label_text = label.get_text(strip=True)
                
                form_elements.append({
                    'field_type': field_type,
                    'label': label_text,
                    'name': input_field.get('name', ''),
                    'placeholder': input_field.get('placeholder', '')
                })
                
            if form_elements:
                interactive_elements.append({
                    'type': 'form',
                    'elements': form_elements
                })
        
        return interactive_elements
    
    def use_llm_to_summarize(self, content: str, elements: List[Dict]) -> str:
        """Use LLM to summarize and format the content for blind users."""
        try:
            # Prepare the elements for the prompt
            elements_text = ""
            for i, elem in enumerate(elements[:20]):  # Limit to first 20 elements
                if elem['type'] == 'link':
                    elements_text += f"{i+1}. Link: {elem['text']} (URL: {elem['href']})\n"
                elif elem['type'] == 'button':
                    elements_text += f"{i+1}. Button: {elem['text']}\n"
                elif elem['type'] == 'form':
                    elements_text += f"{i+1}. Form with fields: "
                    for field in elem['elements']:
                        label = field['label'] or field['placeholder'] or field['name']
                        elements_text += f"{label} ({field['field_type']}), "
                    elements_text = elements_text.rstrip(', ') + "\n"
            
            # Truncate content if too long
            if len(content) > 4000:
                content = content[:4000] + "..."
                
            prompt = f"""
            You are an accessibility assistant for blind users. Extract and summarize the main content 
            and interactive elements from this webpage in a clear, concise format.
            
            WEBPAGE CONTENT:
            {content}
            
            INTERACTIVE ELEMENTS:
            {elements_text}
            
            Please provide:
            1. A brief title/summary of what this page is about
            2. The main content summarized in 3-5 sentences
            3. A structured list of the most important interactive elements
            4. Any other critical information a blind user should know about this page
            
            Format your response in a clean, screen-reader friendly way.
            """
            
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are an accessibility assistant for blind users."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.3
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            print(f"Error using LLM: {e}")
            return f"Error generating summary. Raw content: {content[:500]}..."
    
    def process_url(self, url: str) -> str:
        """Process a URL and return accessible content."""
        html_content = self.fetch_webpage(url)
        if not html_content:
            return "Failed to fetch webpage."
            
        soup = self.preprocess_html(html_content)
        main_content = self.extract_main_content(soup)
        interactive_elements = self.extract_interactive_elements(soup)
        
        return self.use_llm_to_summarize(main_content, interactive_elements)

# Example usage
if __name__ == "__main__":
    import os
    api_key = os.environ.get("OPENAI_API_KEY")
    
    if not api_key:
        print("Please set the OPENAI_API_KEY environment variable.")
        exit(1)
        
    agent = WebsiteAccessibilityAgent(api_key)
    url = "https://example.com"  # Replace with the URL you want to process
    result = agent.process_url(url)
    print(result)