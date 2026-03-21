import time
from collections import defaultdict
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from database import get_products_text, save_order, save_feedback, record_visit
from telegram import send_message, send_photo

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
app = FastAPI()

# ============================================================
# SECURITY 1: CORS - Controls which websites can call this API
# TODO: Replace the placeholder with your actual website domain
# Example: "https://balcimarket.com"
# For now, only localhost is allowed (safe for development)
# ============================================================
ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:8080",
    "https://chatbotbk.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# ============================================================
# SECURITY 2: Rate Limiting - Max 20 requests per IP per minute
# Without this: anyone can spam /chat and drain your OpenAI credits
# With this: after 20 messages in 1 minute, the IP is blocked temporarily
# ============================================================
RATE_LIMIT = 20          # max requests
RATE_WINDOW = 60         # per 60 seconds
rate_tracker = defaultdict(list)  # stores {ip: [timestamps]}

def check_rate_limit(ip: str):
    now = time.time()
    # Keep only timestamps within the last 60 seconds
    rate_tracker[ip] = [t for t in rate_tracker[ip] if now - t < RATE_WINDOW]
    if len(rate_tracker[ip]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")
    rate_tracker[ip].append(now)

# ============================================================
# TOKEN SAVING METHOD 3: Cache products at startup
# Without this: database is called EVERY message (slow + wasteful)
# With this: database is called ONCE when server starts
# Saving: 1 DB query per message → 0 DB queries per message
# ============================================================
try:
    PRODUCTS_CACHE = get_products_text()
    print("Products loaded successfully")
except Exception as e:
    print(f"Warning: Could not load products at startup: {e}")
    PRODUCTS_CACHE = "Products temporarily unavailable."

# ============================================================
# ORDERABLE PRODUCTS: Only these two products can be ordered
# If customer tries to order anything else, bot will politely refuse
# ============================================================
ORDERABLE_PRODUCTS = ["fresh milk 5l", "milk 5l", "milk", "damacana water", "damacana", "water"]


# ============================================================
# TOKEN SAVING METHOD 2: Quick replies dictionary
# Without this: every "hi" or "hello" calls OpenAI API (costs money)
# With this: simple greetings return instant reply for FREE
# Saving: 100% cost for all messages that match this list
# Add more words here anytime to expand the free replies
# ============================================================
QUICK_REPLIES = {
    # English greetings
    "hi": "Hello! Welcome to Balci Market! How can I help you today?",
    "hello": "Hello! Welcome to Balci Market! How can I help you today?",
    "hey": "Hey! Welcome to Balci Market! What can I get for you?",
    # Turkish greetings
    "merhaba": "Merhaba! Balci Market'e hoş geldiniz! Size nasıl yardımcı olabilirim?",
    "selam": "Selam! Balci Market'e hoş geldiniz! Nasıl yardımcı olabilirim?",
    # Arabic greetings
    "مرحبا": "مرحباً! أهلاً في بقالة بالجي! كيف يمكنني مساعدتك؟",
    "السلام عليكم": "وعليكم السلام! أهلاً في بقالة بالجي! كيف يمكنني مساعدتك؟",
    # Goodbyes - English
    "bye": "Goodbye! Have a great day! Hope to see you again at Balci Market!",
    "goodbye": "Goodbye! Have a great day! Hope to see you again!",
    "ok thanks": "You're welcome! Have a great day!",
    "thank you": "You're welcome! Hope to see you again at Balci Market!",
    "thanks": "You're welcome! Have a great day!",
    # Goodbyes - Turkish
    "teşekkürler": "Rica ederim! İyi günler! Tekrar görüşmek üzere!",
    "görüşürüz": "Görüşürüz! İyi günler!",
    # Goodbyes - Arabic
    "شكرا": "عفواً! نراك قريباً في بقالة بالجي!",
    "مع السلامة": "مع السلامة! نراك قريباً!",
}

def get_quick_reply(message: str):
    """
    Check if message matches a quick reply.
    Returns the reply text if found, or None if not found.
    None means we need to call OpenAI.
    """
    cleaned = message.strip().lower()
    return QUICK_REPLIES.get(cleaned, None)


# ============================================================
# TOKEN SAVING METHOD 1: Clean the message before sending to AI
# Without this: "I    want    milk" uses more tokens than needed
# With this: "I    want    milk" → "I want milk" (fewer tokens)
# Also limits message to 500 chars to prevent abuse
# Saving: ~10-50% tokens depending on how messy the message is
# ============================================================
def clean_message(message: str) -> str:
    # Remove extra spaces between words
    message = " ".join(message.split())
    # Remove spaces at start and end
    message = message.strip()
    # Limit to 500 characters max - prevents very long messages wasting tokens
    if len(message) > 500:
        message = message[:500]
    return message


@app.get("/")
def home():
    return {"Message": "Welcome to Balci Market Chatbot!"}


@app.get("/debug/products")
def debug_products():
    count = len(PRODUCTS_CACHE.split("\n")) if PRODUCTS_CACHE != "Products temporarily unavailable." else 0
    return {
        "status": "loaded" if count > 0 else "failed",
        "product_count": count,
        "sample": PRODUCTS_CACHE[:300]
    }


@app.get("/welcome")
def welcome():
    """
    Returns the static welcome message shown when the chatbot first opens.
    NO AI call = zero token cost.
    """
    return {
        "message": "Merhaba komşum! 👋 Ben BALCI Market Dijital Asistanı. Bayram hazırlığın için buradayım. Fiyatlarımızı merak ediyorsan aşağıdaki butonlara basman yeterli. Biz büyük market değiliz ama sizin komşunuzuz, her zaman en iyisini getirmeye çalışıyoruz! 🏠✨"
    }


@app.get("/campaign")
def campaign():
    """
    Returns the static campaign message. NO AI call = zero token cost.
    """
    return {
        "message": "🌟 BAYRAM FIRSATLARI BAŞLADI! 🌟\n\nBayram temizliğinin yıldızları şimdi en dip fiyatlarla dükkanımızda:\n\n👉 Papia T. Kağıdı: 105 TL\n👉 Papia Havlu Kağıt: 135 TL\n👉 Mr. Oxy Yüzey Havlusu: 75 TL\n👉 Viking Çamaşır Suyu: 75 TL\n👉 Penax Gold Kapsül: 199 TL\n👉 Bingo 40'lı Kapsül: 239 TL\n\n✨ Erenler'in en hesaplı adresi! Hayırlı Bayramlar dileriz. ✨"
    }


@app.post("/visit")
def visit():
    """
    Call this from your frontend when the chatbot page loads.
    It adds 1 to today's visit count in the database.
    """
    record_visit()
    return {"status": "ok"}


class ChatMessage(BaseModel):
    role: str    # "user" or "bot"
    text: str

class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []   # full conversation so far (sent from frontend)
    session_id: str = ""
    user_name: str = ""
    user_phone: str = ""


@app.post("/chat")
def chat(request: ChatRequest, req: Request):

    # ---- SECURITY: Rate limit check ----
    check_rate_limit(req.client.host)

    # ---- TOKEN SAVING METHOD 1: Clean message ----
    user_message = clean_message(request.message)

    # ---- TOKEN SAVING METHOD 4: Skip very short messages ----
    # Without this: empty or 1-letter messages still call OpenAI
    # With this: messages under 3 chars are rejected instantly for FREE
    if len(user_message) < 3:
        return {"response": "Could you please tell me more? I am here to help!"}

    # ---- TOKEN SAVING METHOD 2: Quick replies ----
    # Only use quick replies if there is no prior conversation (first message)
    if not request.history:
        quick = get_quick_reply(user_message)
        if quick:
            return {"response": quick}

    # ---- TOKEN SAVING METHOD 3: Use cached products ----
    products = PRODUCTS_CACHE

    # Only reaches here if message needs real AI - costs tokens
    system = SystemMessage(content=f"""Balci Market asistanısın. Sıcak, komşuca bir üslup kullan.
Reply in the SAME language the user writes (EN/TR/AR). Detect from user text, not product names.

Products: {products}

Delivery only: Fresh Milk 5L=200TL, Damacana Water=140TL.

If customer wants to ORDER any other product (not milk or damacana water), reply warmly:
- Tell them that product is not available for online order
- Invite them to visit BALCI Market in-store
- Keep it friendly and warm like a neighbor, not a rejection
- Match their language (TR/EN/AR)

Order steps (only for milk/damacana water): 1)Confirm product 2)Quantity 3)Name 4)Phone 5)House no 6)Payment(cash/transfer) 7)If transfer→slip upload 8)Confirm.

Feedback: if complaint/suggestion/question about shop, prefix reply with [FEEDBACK:complaint], [FEEDBACK:suggestion], or [FEEDBACK:question].

Keep replies short. Suggest related products. End with a helpful question.""")

    # Build message list: system prompt + conversation history + current message
    # This gives the AI full context so it remembers what was said before
    messages = [system]
    for msg in request.history[-10:]:   # only last 10 messages to save tokens
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.text))
        else:
            messages.append(AIMessage(content=msg.text))
    messages.append(HumanMessage(content=user_message))

    response = llm.invoke(messages)
    reply = response.content

    # Check if AI detected feedback - save silently + notify owner
    if reply.startswith("[FEEDBACK:"):
        end = reply.index("]")
        tag = reply[1:end]
        feedback_type = tag.split(":")[1]
        clean_reply = reply[end+1:].strip()

        save_feedback(feedback_type, user_message, request.user_name, request.user_phone, request.session_id)
        send_message(f"""NEW FEEDBACK - Balci Market

Type: {feedback_type}
Message: {user_message}
From: {request.user_name or "Anonymous"}
Phone: {request.user_phone or "Unknown"}
""")
        return {"response": clean_reply}

    return {"response": reply}


# Create uploads folder for payment slips
Path("uploads").mkdir(exist_ok=True)


class OrderRequest(BaseModel):
    customer_name: str
    phone: str
    house_no: str
    product: str
    quantity: int
    payment: str


@app.post("/order")
async def order(
    req: Request,
    customer_name: str = Form(...),
    phone: str = Form(...),
    house_no: str = Form(...),
    product: str = Form(...),
    quantity: int = Form(...),
    payment: str = Form(...),
    slip: UploadFile = File(None)
):
    # ---- SECURITY: Rate limit check ----
    check_rate_limit(req.client.host)

    # ---- SECURITY: Input length validation ----
    if len(customer_name) > 100 or len(phone) > 20 or len(house_no) > 50 or len(product) > 100:
        raise HTTPException(status_code=400, detail="Input too long.")

    # ---- SECURITY: File type check — only images and PDF allowed ----
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}
    if slip and slip.filename:
        ext = slip.filename.split(".")[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Only JPG, PNG, or PDF files are allowed for payment slip.")

    slip_filename = ""

    # ---- LOCK: Only allow ordering Fresh Milk 5L or Damacana Water ----
    # This prevents orders for products we don't deliver
    if not any(p in product.lower() for p in ORDERABLE_PRODUCTS):
        return {
            "status": "error",
            "message": "Üzgünüm komşum, şu an sadece Taze Süt 5L ve Damacana Su siparişi alabiliyoruz. 🙏 Diğer ürünlerimiz için sizi dükkanımızda görmekten çok mutlu oluruz! Kapımız her zaman açık. 🏠✨"
        }

    # If payment is transfer, save the slip file to uploads folder
    if payment == "transfer" and slip:
        slip_filename = f"slip_{customer_name}_{phone}.{slip.filename.split('.')[-1]}"
        with open(f"uploads/{slip_filename}", "wb") as f:
            f.write(await slip.read())

    # Save order to database
    save_order(customer_name, phone, house_no, product, quantity, slip_filename)

    # Send Telegram notification to owner
    message = f"""NEW ORDER - Balci Market

Name: {customer_name}
Phone: {phone}
House No: {house_no}
Product: {product}
Quantity: {quantity}
Payment: {payment}
"""
    if payment == "transfer" and slip_filename:
        send_photo(f"uploads/{slip_filename}", message)
    else:
        send_message(message)

    return {"status": "success", "message": "Order received!"}