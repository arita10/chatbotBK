import os
import time
from collections import defaultdict
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from database import get_products_text, save_order, save_feedback, record_visit, get_cheaper_products, save_chat
from telegram import send_message, send_photo, send_document

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
    "https://balci-market-bot.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
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

# Pre-compute price comparison at startup so /compare is instant
try:
    COMPARE_CACHE = get_cheaper_products(limit=10)
    cheaper_count = len(COMPARE_CACHE.get("cheaper", []))
    equal_count = len(COMPARE_CACHE.get("equal", []))
    print(f"Price comparison loaded: {cheaper_count} cheaper, {equal_count} equal products found")
except Exception as e:
    print(f"Warning: Could not load price comparison at startup: {e}")
    COMPARE_CACHE = {"cheaper": [], "equal": []}

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


@app.get("/debug/compare")
def debug_compare():
    """Show all matched pairs (cheaper, equal, and MORE EXPENSIVE) for debugging."""
    import requests as req_lib
    from rapidfuzz import fuzz

    headers = {
        "apikey": os.getenv("SUPABASE_KEY"),
        "Authorization": f"Bearer {os.getenv('SUPABASE_KEY')}",
    }
    supabase_url = os.getenv("SUPABASE_URL")

    our_products = req_lib.get(
        f"{supabase_url}/rest/v1/ch_products?select=product_name,sale_price",
        headers=headers, timeout=15
    ).json()

    comp_products = req_lib.get(
        f"{supabase_url}/rest/v1/sp_products?select=product_name,market_name,latest_price&limit=3000",
        headers=headers, timeout=15
    ).json()

    # Find all matches above 60% for our products that contain 'essen'
    our_essen = [p for p in our_products if 'essen' in p.get('product_name', '').lower()]
    matches = []
    for our in our_essen:
        our_name = our['product_name']
        our_price = float(our.get('sale_price') or 0)
        best_score = 0
        best = None
        for comp in comp_products:
            score = fuzz.token_sort_ratio(our_name.lower(), comp['product_name'].lower())
            if score > best_score:
                best_score = score
                best = comp
        matches.append({
            "our": our_name,
            "our_price": our_price,
            "best_match": best['product_name'] if best else None,
            "best_market": best['market_name'] if best else None,
            "comp_price": best['latest_price'] if best else None,
            "score": best_score,
        })

    markets = list(set(p.get('market_name','') for p in comp_products))
    our_sample = [p['product_name'] for p in our_products[:30]]
    comp_sample = [f"{p['product_name']} ({p['market_name']})" for p in comp_products[:30]]

    # Show ALL matches (cheaper, equal, expensive) for all our products
    all_matches = []
    for our in our_products:
        our_name = our['product_name']
        our_price = float(our.get('sale_price') or 0)
        our_brand = our_name.strip().split()[0].lower() if our_name.strip() else ''
        best_score = 0
        best = None
        for comp in comp_products:
            cn = comp.get('product_name','')
            if our_brand and our_brand not in cn.lower():
                continue
            score = fuzz.token_sort_ratio(our_name.lower(), cn.lower())
            if score > best_score:
                best_score = score
                best = comp
        if best_score >= 60:
            try:
                cp = float(str(best['latest_price']).replace(',','.').replace(' TL','').strip())
            except:
                cp = None
            all_matches.append({
                "our": our_name, "our_price": our_price,
                "comp": best['product_name'], "market": best['market_name'],
                "comp_price": cp, "score": best_score,
                "cheaper": our_price < cp if cp else None
            })

    all_matches.sort(key=lambda x: x['score'], reverse=True)

    return {
        "our_product_count": len(our_products),
        "comp_product_count": len(comp_products),
        "markets_in_sp": markets,
        "our_sample": our_sample,
        "comp_sample": comp_sample,
        "all_matches_above_60": all_matches[:50],
    }


@app.get("/welcome")
def welcome(session_id: str = ""):
    """
    Returns the static welcome message shown when the chatbot first opens.
    NO AI call = zero token cost.
    """
    msg = "Merhaba komşum! 👋 Ben BALCI Market'in dijital asistanıyım. Hoş geldiniz! 🛒\n\nFiyat sormak, sipariş vermek ya da aklınıza takılan bir şeyi sormak için buradayım. Biz büyük market değiliz ama sizin komşunuzuz — her zaman güler yüzle, en iyi fiyatla! 🏠✨\n\nNasıl yardımcı olabilirim?"
    try:
        save_chat(session_id, "[opened chat]", msg)
    except Exception:
        pass
    return {"message": msg}


class LogRequest(BaseModel):
    session_id: str = ""
    user_message: str = ""
    bot_reply: str = ""

@app.post("/log")
def log_chat(request: LogRequest):
    """Silently save a conversation turn — used for button clicks that bypass /chat."""
    try:
        save_chat(request.session_id, request.user_message[:500], request.bot_reply[:500])
    except Exception:
        pass
    return {"status": "ok"}


@app.get("/compare")
def compare(session_id: str = ""):
    """Returns pre-computed price comparison from startup cache — instant response."""
    cheaper = COMPARE_CACHE.get("cheaper", [])
    equal = COMPARE_CACHE.get("equal", [])

    if not cheaper and not equal:
        return {"message": "Şu an karşılaştırma verisi bulunamadı."}

    lines = []

    if cheaper:
        lines.append("🏆 BİZDE DAHA UCUZ:\n")
        for r in cheaper:
            line = (
                f"✅ {r['our_name']}\n"
                f"   Bizde: {r['our_price']:.2f} TL | {r['comp_market']}: {r['comp_price']:.2f} TL | 💰 {r['savings']:.2f} TL tasarruf!"
            )
            if r.get("comp_url"):
                line += f"\n   🔗 {r['comp_market']}: {r['comp_url']}"
            lines.append(line)


    msg = "\n".join(lines)
    try:
        save_chat(session_id, "💸 Rakipten Ucuz Ürünler", msg)
    except Exception:
        pass
    return {"message": msg}


@app.get("/campaign")
def campaign(session_id: str = ""):
    """
    Returns the static campaign message. NO AI call = zero token cost.
    """
    msg = (
        "🍫 ÇİKOLATA ŞENLİĞİ — SADECE 1 HAFTA! 🍫\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🟡 ÜLKER\n"
        "• Bol Sütlü Kare 60g        67 → 50 TL 🔥\n"
        "• Antep Fıstıklı 14g         22 → 18 TL\n"
        "• Sütlü Çikolata 33g         47 → 40 TL\n\n"
        "🔴 ETİ\n"
        "• Sütlü Çikolata 60g         70 → 50 TL 🔥\n"
        "• Fındıklı Kare 60g          70 → 50 TL 🔥\n"
        "• Antep Fıstıklı 60g        105 → 90 TL\n"
        "• Karam Bitter Antep %54 60g 102 → 90 TL\n"
        "• Çikolata Bademli 30g       55 → 50 TL\n"
        "• Çikolata 7g                sadece 8 TL 🎉\n"
        "• İçibol %27 Fındıklı       39.90 → 35 TL\n\n"
        "🌽 DORITOS\n"
        "• Tüm Doritos ürünleri       5 TL indirim!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⏰ Kampanya sadece 1 hafta geçerli!\n"
        "🏠 Erenler'in en hesaplı adresi — Balci Market ✨"
    )
    try:
        save_chat(session_id, "🎉 Kampanyalar", msg)
    except Exception:
        pass
    return {"message": msg}


@app.post("/visit")
def visit(req: Request):
    """
    Call this from your frontend when the chatbot page loads.
    Records a visit row with timestamp and user agent.
    """
    ua = req.headers.get("user-agent", "")
    record_visit(ua)
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
            try:
                save_chat(request.session_id, user_message, quick)
            except Exception:
                pass
            return {"response": quick}

    # ---- TOKEN SAVING METHOD 3: Use cached products ----
    products = PRODUCTS_CACHE

    # Only reaches here if message needs real AI - costs tokens
    system = SystemMessage(content=f"""Sen Balci Market'in neşeli, komşuca, biraz da esprili dijital asistanısın. 🛒
Dükkanın sahibi Samet Abi — samimi, yardımsever, mütevazı ve her zaman güler yüzlü biri.
Sen de onun ruhunu yansıt: sıcak, alçakgönüllü, biraz esprili ama her zaman saygılı ve yardımsever.
Komşuya konuşur gibi konuş — resmi değil, ama saygısız da değil. "Komşum", "efendim" gibi hitaplar kullan.
Sohbet içinde uygun yerlerde "Samet Abi" adını doğal olarak kullan — örneğin detay bilmediğinde "Samet Abi'ye sorabilirsiniz", dükkanı önerirken "Samet Abi sizi bekliyor" gibi. Ama her cümlede kullanma, sadece doğal geldiğinde.
Reply in the SAME language the user writes (EN/TR/AR). Detect from user text, not product names.

Çalışma Saatleri:
- Pazartesi - Cuma: 07:30 - 22:30
- Cumartesi: 09:00 - 22:30
- Pazar: 10:00 - 22:30

KAPALI OLDUĞUMUZ SAATLER: Eğer kullanıcı mesai saatleri dışında mesaj atarsa (örn. gece 23:00, sabah 06:00 gibi):
- Şu an dükkanın kapalı olduğunu nazikçe ve esprili bir şekilde söyle
- Özür dile, rahatsızlık için üzgün olduğunu belirt
- Çalışma saatlerini hatırlat
- Yarın o saatte görmeyi umduğunu sıcakça yaz
- Örnek üslup: "Aman komşum, şu saatte ben de biraz dinleniyorum 😴 Yarın [saat] gibi burada olacağım, seni bekliyorum!"

DETAY BİLMEDİĞİM KONULAR: Eğer kullanıcı çok detaylı veya bilmediğin bir şey sorarsa:
- Dürüstçe söyle, ben sadece bir chatbotum, her şeyi bilemem 🤖
- Komik ve alçakgönüllü bir üslupla kabul et
- Dükkanı aramalarını veya bizzat gelmeleri öner
- Örnek: "Vay be, bu soruyu bana sordun ama ben sadece mütevazı bir chatbotum 🤖😅 Bu konuda seni dükkana yönlendireyim!"

HATA YAPARSAM: Eğer kullanıcı "yanlış söyledin", "hata yaptın", "seni yenile", "refresh" gibi bir şey derse:
- Özür dile, esprili ve nazik bir şekilde
- "Kendimi yeniliyorum, bir saniye! 🔄" gibi bir şey söyle
- Kullanıcıyı tekrar sorusunu sormaya davet et

Products: {products}

Delivery only: Fresh Milk 5L=200TL, Damacana Water=140TL.

IMPORTANT: If customer is just ASKING about a product (e.g. "X var mı?", "do you have X?", "X fiyatı?"), answer normally using the product list above. DO NOT say it's unavailable for order unless they explicitly say "sipariş", "order", "almak istiyorum", "teslim et" etc.

Only when customer explicitly wants to PLACE AN ORDER for a product other than milk or damacana water, reply warmly:
- Tell them that product is not available for online order/delivery
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
        try:
            save_chat(request.session_id, user_message, clean_reply)
        except Exception:
            pass
        return {"response": clean_reply}

    try:
        save_chat(request.session_id, user_message, reply)
    except Exception:
        pass
    return {"response": reply}


# Create uploads folder for payment slips and print files
Path("uploads").mkdir(exist_ok=True)
Path("prints").mkdir(exist_ok=True)


@app.post("/print")
async def print_request(
    req: Request,
    location: str = Form("inshop"),  # 'inshop' or 'delivery'
    customer_name: str = Form(""),
    phone: str = Form(""),
    house_no: str = Form(""),
    print_type: str = Form("Siyah Beyaz (5 TL/sayfa)"),
    copies: int = Form(1),
    notes: str = Form(""),
    file: UploadFile = File(...),
):
    check_rate_limit(req.client.host)

    if len(customer_name) > 100 or len(phone) > 20 or len(house_no) > 50:
        raise HTTPException(status_code=400, detail="Input too long.")

    # Allow common file types for printing
    ALLOWED = {"jpg", "jpeg", "png", "pdf", "doc", "docx", "xls", "xlsx", "txt"}
    ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if ext not in ALLOWED:
        raise HTTPException(status_code=400, detail="Desteklenmeyen dosya türü.")

    # Save file
    safe_prefix = f"{customer_name}_{phone}" if customer_name else "inshop"
    safe_name = f"print_{safe_prefix}.{ext}"
    file_path = f"prints/{safe_name}"
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # Build Telegram notification
    if location == "delivery":
        caption = f"""🖨️ YENİ BASKI TALEBİ (Eve Teslimat) - Balci Market

Ad Soyad: {customer_name}
Telefon: {phone}
Daire / Ev No: {house_no}
Baskı Türü: {print_type}
Kopya Sayısı: {copies}
Notlar: {notes or "Yok"}
Dosya: {file.filename}"""
    else:
        caption = f"""🖨️ YENİ BASKI TALEBİ (Mağazadan) - Balci Market

Baskı Türü: {print_type}
Kopya Sayısı: {copies}
Notlar: {notes or "Yok"}
Dosya: {file.filename}"""

    send_message(caption)
    doc_caption = f"📎 {file.filename}" + (f" — {customer_name} ({phone})" if customer_name else "")
    send_document(file_path, caption=doc_caption)

    return {"status": "ok", "message": "Baskı talebiniz alındı! En kısa sürede hazırlanacak. 🖨️"}


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
    db_saved = True
    try:
        save_order(customer_name, phone, house_no, product, quantity, slip_filename)
    except Exception as e:
        db_saved = False
        print(f"[order DB SAVE FAILED] {e}")

    # Send Telegram notification to owner
    db_warning = "" if db_saved else "\n⚠️ UYARI: Sipariş veritabanına kaydedilemedi!"
    message = f"""NEW ORDER - Balci Market

Name: {customer_name}
Phone: {phone}
House No: {house_no}
Product: {product}
Quantity: {quantity}
Payment: {payment}{db_warning}
"""
    if payment == "transfer" and slip_filename:
        send_photo(f"uploads/{slip_filename}", message)
    else:
        send_message(message)

    return {"status": "success", "message": "Order received!"}