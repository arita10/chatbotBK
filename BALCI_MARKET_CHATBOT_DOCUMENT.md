# Balci Market Chatbot — Full App Documentation

**Version:** 1.0
**Date:** March 2026
**Owner:** Samet Abi — Balci Market, Erenler, Sakarya

---

## 1. What Is This App?

Balci Market Chatbot is an AI-powered customer assistant for Balci Market. Customers can:

- Ask about products and prices
- Place home delivery orders (milk and water)
- Request print services (in-store or home delivery)
- Give feedback or complaints
- See promotions and price comparisons vs competitors

The bot speaks **Turkish, English, and Arabic** — it auto-detects the customer's language.

---

## 2. Architecture Overview

```
Customer Browser
      ↓
  Vercel (React Frontend)
      ↓  REST API calls
  Render (FastAPI Backend / Python)
      ↓
  Supabase (PostgreSQL Database)
      +
  Telegram Bot (Owner Notifications)
      +
  OpenAI GPT-4o-mini (AI Replies)
```

---

## 3. Deployment

| Part | Platform | URL |
|------|----------|-----|
| Frontend (React) | Vercel | https://balci-market-bot.vercel.app |
| Backend (FastAPI) | Render | https://chatbotbk.onrender.com |
| Database | Supabase | zaxrrulnsporoqpxjfms.supabase.co |

**Frontend auto-deploys** from GitHub (`arita10/chatbotFrt`) when you push to `master` branch.
**Backend auto-deploys** from its own GitHub repo when you push changes.

---

## 4. Backend (Python / FastAPI)

**Location:** `c:\Users\msapi\OneDrive\Documents\Balci market\Chatbot\`

### 4.1 Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI server — all API endpoints and chat logic |
| `database.py` | All Supabase database read/write functions |
| `telegram.py` | Sends notifications to owner via Telegram |
| `requirements.txt` | Python package dependencies |
| `.env` | Secret keys (never share this file) |

### 4.2 Python Packages

| Package | Purpose |
|---------|---------|
| `fastapi` | Web server framework |
| `uvicorn` | Runs the FastAPI server |
| `langchain-openai` | Connects to OpenAI GPT-4o-mini |
| `openai` | OpenAI API client |
| `requests` | HTTP calls to Supabase REST API |
| `python-multipart` | Handles file uploads (slip, print files) |
| `rapidfuzz` | Fuzzy product name matching for price comparison |
| `python-dotenv` | Loads secrets from `.env` file |
| `pydantic` | Request/response data validation |

### 4.3 API Endpoints

| Method | Endpoint | Description | AI Cost? |
|--------|----------|-------------|----------|
| GET | `/` | Health check | No |
| GET | `/welcome` | Welcome message | No |
| GET | `/campaign` | Current promotions | No |
| GET | `/compare` | Products cheaper than competitors | No |
| GET | `/debug/products` | Shows product count loaded | No |
| POST | `/chat` | AI chat reply | Yes (GPT-4o-mini) |
| POST | `/order` | Submit a delivery order | No |
| POST | `/print` | Submit a print job | No |
| POST | `/visit` | Record a page visit | No |

### 4.4 `/chat` Endpoint — How It Works

**Request body:**
```json
{
  "message": "Sütün fiyatı nedir?",
  "history": [{ "role": "user", "text": "..." }, { "role": "bot", "text": "..." }],
  "session_id": "abc123xyz",
  "user_name": "",
  "user_phone": ""
}
```

**Processing steps (in order):**
1. Rate limit check (max 20 requests/IP/minute)
2. Clean message (remove extra spaces, cap at 500 chars)
3. Reject if message under 3 characters
4. Check quick replies dictionary — return instant reply if match (FREE, no AI)
5. If none of above matched → call OpenAI GPT-4o-mini with system prompt + last 10 history messages
6. If AI reply contains `[FEEDBACK:...]` tag → save to feedback table + notify owner on Telegram
7. Save conversation to `ch_chatbot_conversations` table
8. Return reply to frontend

**Token cost saving methods:**
- Quick replies for greetings/goodbyes (no OpenAI call)
- Product list cached at startup (no DB query per message)
- Price comparison cached at startup
- History limited to last 10 messages
- Messages cleaned and capped at 500 chars

### 4.5 Security

- **CORS:** Only allows requests from `localhost`, Render, and Vercel — blocks all other websites
- **Rate limiting:** Max 20 messages per IP per 60 seconds — protects against spam and OpenAI credit drain
- **Input validation:** Name max 100 chars, phone max 20 chars, address max 50 chars
- **File uploads:** Only JPG, PNG, PDF allowed for order slips; JPG/PNG/PDF/DOC/DOCX/XLS/XLSX/TXT for print jobs

### 4.6 AI Personality (System Prompt Summary)

- Name: Balci Market's digital assistant
- Owner: Samet Abi — friendly, humble, helpful neighbor
- Style: Warm, neighborly, slightly humorous. Uses "komşum", "efendim"
- Mentions "Samet Abi" naturally when relevant (not every sentence)
- If closed hours: politely apologizes with humor, states opening hours
- If doesn't know something: honestly admits it, suggests calling or visiting
- Orderable products via chat flow: Fresh Milk 5L (200 TL), Damacana Water (140 TL)
- Other products: customer must visit store

**Working hours communicated to customers:**
- Monday–Friday: 07:30 – 22:30
- Saturday: 09:00 – 22:30
- Sunday: 10:00 – 22:30

---

## 5. Database (Supabase PostgreSQL)

**Connection:** Supabase REST API (no direct PostgreSQL connection)
**Auth:** anon key in `SUPABASE_KEY` environment variable

### 5.1 Tables

#### `ch_products`
Stores Balci Market's product catalog.

| Column | Type | Description |
|--------|------|-------------|
| product_name | text | Product name |
| sale_price | numeric | Selling price in TL |

#### `ch_chatbot_orders`
Delivery orders placed via the chatbot.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Auto-increment |
| customer_name | text | Customer full name |
| phone | text | Phone number (05xxxxxxxxx) |
| house_no | text | Apartment/house address |
| product | text | Product ordered |
| quantity | int | Number of units |
| slip_filename | text | Payment slip filename (if transfer) |
| created_at | timestamp | Order time |

#### `ch_chatbot_conversations`
Every chat message saved for analytics.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Auto-increment |
| session_id | text | Unique per browser tab |
| user_message | text | What customer wrote (max 1000 chars) |
| bot_reply | text | What bot replied (max 2000 chars) |
| created_at | timestamp | Message time |

#### `ch_chatbot_feedback`
Complaints, suggestions, questions detected by AI.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Auto-increment |
| feedback_type | text | "complaint", "suggestion", or "question" |
| message | text | Customer's original message |
| user_name | text | Customer name (if known) |
| user_phone | text | Customer phone (if known) |
| session_id | text | Session identifier |
| created_at | timestamp | Time of feedback |

#### `ch_chatbot_visits`
Page visit tracking.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Auto-increment |
| user_agent | text | Browser/device info |
| created_at | timestamp | Visit time |

#### `sp_products`
Competitor product prices (scraped externally, used for price comparison).

| Column | Type | Description |
|--------|------|-------------|
| product_name | text | Competitor product name |
| market_name | text | Competitor market name |
| latest_price | text | Competitor price |
| product_url | text | Link to competitor product |

---

## 6. Frontend (React)

**Location:** `c:\Users\msapi\OneDrive\Documents\Balci market\ChatBotFront\`
**GitHub:** `arita10/chatbotFrt` (master branch)

### 6.1 Files

| File | Purpose |
|------|---------|
| `src/App.js` | Main app — state management, session ID, all event handlers |
| `src/api.js` | All API calls to backend (sendChat, submitOrder, etc.) |
| `src/components/ChatWindow.js` | Displays messages with auto-scroll |
| `src/components/InputBar.js` | Text input + send button + order shortcut button |
| `src/components/MessageBubble.js` | Single chat message bubble (user or bot) |
| `src/components/OrderForm.js` | Popup form to place a delivery order |
| `src/components/PrintForm.js` | Popup form to request a print job |
| `src/styles/App.css` | Global layout and header styles |
| `src/styles/ChatWindow.css` | Chat area styles |
| `src/styles/InputBar.css` | Input bar styles |
| `src/styles/MessageBubble.css` | Message bubble styles |
| `src/styles/OrderForm.css` | Order and print form styles |

### 6.2 Session Tracking

A unique `SESSION_ID` is generated once when the browser tab opens:
```js
const SESSION_ID = Math.random().toString(36).substring(2) + Date.now().toString(36);
```
This is sent with every `/chat` request so all messages from one conversation are linked together in the database.

### 6.3 Quick Action Buttons (Suggestion Chips)

Shown when input is empty and bot is not loading:

| Button | Action |
|--------|--------|
| Taze Süt 5L sipariş ver | Opens order form with Milk pre-selected |
| Damacana Su sipariş ver | Opens order form with Water pre-selected |
| Baskı Talebi | Opens print form |
| Sütün fiyatı nedir? | Sends to AI chat |
| Hangi ürünleriniz var? | Sends to AI chat |
| Çalışma saatleri nedir? | Sends to AI chat |
| Rakipten Ucuz Ürünler | Fetches `/compare` (no AI cost) |
| Kampanyalar | Fetches `/campaign` (no AI cost) |

### 6.4 Order Form

Triggered when user types order-related keywords or clicks the cart button.

**Fields:**
- Product: Fresh Milk 5L (200 TL) or Damacana Water (140 TL)
- Quantity (with +/− buttons, shows running total)
- Full name (min 2 chars)
- Phone (must be valid Turkish: 05xxxxxxxxx)
- House/apartment number
- Payment: Cash on delivery or Bank transfer
- Payment slip upload (JPG/PNG/PDF) — only shown for bank transfer

**After submit:**
- Order saved to `ch_chatbot_orders` table
- Telegram notification sent to owner (with slip photo if transfer)
- Customer info saved to `localStorage` for next visit

### 6.5 Print Form

**Fields:**
- Location: In-store (no personal info needed) or Home delivery (name/phone/address required)
- Print type: Black & White (5 TL/page) or Color (10 TL/page)
- Number of copies (with running total)
- Notes (optional, e.g. "double-sided, A4")
- File upload: JPG, PNG, PDF, DOC, DOCX, XLS, XLSX, TXT

**After submit:**
- Telegram notification sent to owner with file attached

### 6.6 Customer Info Persistence

Name, phone, and house number are stored in browser `localStorage` under key `balci_customer`. The order and print forms pre-fill from this on return visits.

---

## 7. Telegram Notifications

Owner receives instant Telegram messages for:

| Event | What is sent |
|-------|-------------|
| New order (cash) | Text with customer name, phone, address, product, quantity |
| New order (transfer) | Same + payment slip photo |
| New feedback | Text with feedback type, message, customer info |
| New print request (in-store) | Text + file attached |
| New print request (delivery) | Text with customer info + file attached |

---

## 8. Environment Variables

Stored in `Chatbot/.env` — **never commit this file to GitHub.**

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key (for GPT-4o-mini) |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon key |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat/group ID for owner alerts |
| `LANGCHAIN_TRACING_V2` | Set to `true` to enable LangSmith monitoring |
| `LANGCHAIN_API_KEY` | LangSmith API key (optional, for monitoring) |
| `LANGCHAIN_PROJECT` | LangSmith project name (`balci-chatbot`) |

---

## 9. How to Run Locally

### Backend
```bash
cd "c:\Users\msapi\OneDrive\Documents\Balci market\Chatbot"
source venv/Scripts/activate        # Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
Backend will be at: http://localhost:8000

### Frontend
```bash
cd "c:\Users\msapi\OneDrive\Documents\Balci market\ChatBotFront"
npm install
npm start
```
Frontend will be at: http://localhost:3000
(Proxy in `package.json` forwards API calls to Render backend automatically in dev mode)

---

## 10. How to Deploy

### Frontend (Vercel)
Push changes to GitHub — Vercel auto-deploys:
```bash
cd "c:\Users\msapi\OneDrive\Documents\Balci market\ChatBotFront"
git add src/App.js src/api.js   # (or whichever files changed)
git commit -m "Your message"
git push origin master
```
Vercel builds and deploys in ~1-2 minutes.

### Backend (Render)
Push changes to backend GitHub repo — Render auto-deploys.
No manual step needed.

---

## 11. Orderable Products (Home Delivery Only)

| Product | Price |
|---------|-------|
| Fresh Milk 5L (Taze Süt 5L) | 200 TL |
| Damacana Water (Damacana Su) | 140 TL |

All other products are available **in-store only**. If a customer tries to order anything else through chat, the bot politely declines and invites them to visit.

---

## 12. Price Comparison Feature

The `/compare` endpoint compares `ch_products` (Balci Market) vs `sp_products` (competitors) using fuzzy name matching (`rapidfuzz`).

**Rules for a valid match:**
- Brand name (first word) must be the same
- Product weight/volume unit must match (e.g. both 5L, both 500g)
- Quantity within 10% tolerance
- Fuzzy name similarity score must be 80% or higher
- Bulk/multi-packs from competitors are excluded

**Result:** Shows which Balci Market products are cheaper, and by how much (TL saved).

---

*Document generated March 2026. For questions contact Samet Abi at Balci Market, Erenler, Sakarya.*