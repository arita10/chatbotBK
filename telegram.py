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

if __name__ == "__main__":
    send_message("Hello from Balci Market Chatbot!")
    print("Message sent to Telegram!")