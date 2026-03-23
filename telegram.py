import os 
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_message(text):
    #Send a text message to the owner
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text
    })
    
def send_photo(photo_path, caption):
    #Send a photo to the owner
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "caption": caption
        }, files={"photo": photo})

def send_document(file_path, caption):
    """Send any file (PDF, Word, image, etc.) to the owner via Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(file_path, "rb") as f:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "caption": caption
        }, files={"document": f})

if __name__ == "__main__":
    send_message("Hello from Balci Market Chatbot!")
    print("Message sent to Telegram!")