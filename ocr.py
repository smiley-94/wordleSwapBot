import json
import base64
import io
import re
import logging
import requests
from PIL import ImageFilter
import ollama
from config import OLLAMA_API_KEY, OLLAMA_MODEL, OLLAMA_HOST

logger = logging.getLogger(__name__)

def preprocess_image(img):
    """Preprocess image for better OCR results"""
    img = img.convert("L")
    threshold = 200
    img = img.point(lambda x: 255 if x > threshold else 0)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    return img.point(lambda x: 255 if x > 128 else 0)

def encode_image_b64(img):
    """Encode PIL image to base64 string"""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def extract_first_json(text):
    """Extract JSON array from LLM response"""
    match = re.search(r'\[\s*"[^"]*"(?:\s*,\s*"[^"]*")*\s*\]', text)
    return match.group(0) if match else text.strip()

def clean_word(word):
    """Clean and validate word"""
    return ''.join(filter(str.isalpha, word)).upper()

def run_ocr(img_b64):
    """Run OCR on base64 encoded image using Ollama"""
    client = ollama.Client(
        host=OLLAMA_HOST,
        headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"}
    )

    messages = [
        {
            "role": "system",
            "content": "You are an expert OCR assistant specialized in reading Wordle game grids. "
                       "The image shows white letters on black background. "
                       "Focus on extracting exactly 5 letters per word from the grid. "
                       "The grid has up to 6 rows of 5 letters each. "
                       "Respond ONLY with a JSON array like [\"WORD1\", \"WORD2\"]. "
                       "No explanations, no markdown, just the JSON array."
        },
        {
            "role": "user",
            "content": (
                "Read this Wordle grid image carefully. It shows a grid with up to 6 rows "
                "and exactly 5 columns. Each cell contains one English letter in WHITE on BLACK background.\n\n"
                "Extract ONLY the words that have been entered in the grid, row by row.\n"
                "If a row is not completely filled, skip it.\n"
                "If letters appear unclear or partially obscured, make reasonable guesses.\n\n"
                "Return ONLY a valid JSON array containing the 5-letter words found.\n"
                "Example correct output: [\"CRANE\", \"SLATE\", \"HELLO\"]\n"
                "DO NOT include any other text, explanations, or markdown."
            ),
            "images": [img_b64]
        }
    ]

    try:
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            format="json",
            stream=False
        )
    except Exception as exc:
        raise RuntimeError(f"Ollama request failed: {exc}")

    raw = response.get("message", {}).get("content", "")
    if not raw:
        raise RuntimeError("Empty response from the model.")

    cleaned_raw = extract_first_json(raw)

    try:
        words = json.loads(cleaned_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Response is not valid JSON: {exc}\nContent:\n{cleaned_raw}")

    if not isinstance(words, list):
        raise RuntimeError(f"Expected a list, got {type(words).__name__}")

    cleaned_words = []
    for w in words:
        if isinstance(w, str):
            cleaned = clean_word(w)
            if len(cleaned) == 5 and cleaned.isalpha():
                cleaned_words.append(cleaned)

    return cleaned_words

def get_nyt_solution(date_str):
    """Get NYT Wordle solution for a specific date"""
    url = f"https://www.nytimes.com/svc/wordle/v2/{date_str}.json"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get("solution", "").upper()
    except Exception as e:
        logger.warning(f"Failed to fetch NYT solution: {e}")
    return None
