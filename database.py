import os
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Headers used for every Supabase REST API call
def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def get_product():
    # Fetch all products from ch_products table via Supabase REST API
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/ch_products?select=product_name,sale_price",
        headers=_headers(),
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def get_products_text():
    products = get_product()

    if not products:
        return "No products available."

    lines = []
    for p in products:
        name = p.get("product_name") or "Unknown"
        price = p.get("sale_price")

        if price:
            upper = float(price)
            lower = upper - 2  # show range starting 2 TL below actual price
            line = f"- {name}: {lower:.0f} - {upper:.0f} TL"
        else:
            line = f"- {name}: price on request"

        lines.append(line)

    return "\n".join(lines)


def save_order(customer_name, phone, house_no, product, quantity, slip_filename):
    data = {
        "customer_name": customer_name,
        "phone": phone,
        "house_no": house_no,
        "product": product,
        "quantity": quantity,
        "slip_filename": slip_filename,
    }
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/ch_chatbot_orders",
        headers={**_headers(), "Prefer": "return=minimal"},
        json=data,
        timeout=10,
    )
    if not response.ok:
        print(f"[save_order ERROR] {response.status_code}: {response.text}")
    response.raise_for_status()


def save_feedback(feedback_type, message, user_name="", user_phone="", session_id=""):
    data = {
        "feedback_type": feedback_type,
        "message": message,
        "user_name": user_name,
        "user_phone": user_phone,
        "session_id": session_id,
    }
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/ch_chatbot_feedback",
        headers={**_headers(), "Prefer": "return=minimal"},
        json=data,
        timeout=10,
    )
    if not response.ok:
        print(f"[save_feedback ERROR] {response.status_code}: {response.text}")
    response.raise_for_status()


def save_chat(session_id, user_message, bot_reply):
    data = {
        "session_id": session_id,
        "user_message": user_message[:1000],
        "bot_reply": bot_reply[:2000],
    }
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/ch_chatbot_conversations",
        headers={**_headers(), "Prefer": "return=minimal"},
        json=data,
        timeout=10,
    )
    if not response.ok:
        print(f"[save_chat ERROR] {response.status_code}: {response.text}")


def record_visit(user_agent=""):
    data = {"user_agent": user_agent[:300] if user_agent else ""}
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/ch_chatbot_visits",
        headers={**_headers(), "Prefer": "return=minimal"},
        json=data,
        timeout=10,
    )
    if not response.ok:
        print(f"[record_visit ERROR] {response.status_code}: {response.text}")


def _extract_unit(name):
    """Extract weight/volume unit from product name e.g. '50g', '1kg', '1l', '500ml'"""
    import re
    match = re.search(r'(\d+[\.,]?\d*)\s*(kg|g|ml|l|lt|cl|adet|pk|paket)\b', name.lower())
    if match:
        qty = float(match.group(1).replace(",", "."))
        unit = match.group(2)
        if unit == "kg":
            return qty * 1000, "g"
        if unit in ("l", "lt"):
            return qty * 1000, "ml"
        return qty, unit
    # Fallback: bare number >= 50 likely means grams (e.g. "kaşar 400 peyniri")
    bare = re.search(r'\b(\d{2,4})\b', name)
    if bare:
        qty = float(bare.group(1))
        if 50 <= qty <= 5000:
            return qty, "g"
    return None, None


def _extract_brand(name):
    """Extract first word as brand name (lowercase)"""
    words = name.strip().split()
    return words[0].lower() if words else ""


def get_cheaper_products(limit=10):
    """
    Compare ch_products with sp_products using fuzzy name matching.
    Only compares products with matching units/weights.
    Returns only products where Balci Market is cheaper than competitors.
    """
    from rapidfuzz import fuzz

    our_resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/ch_products?select=product_name,sale_price",
        headers=_headers(), timeout=10
    )
    our_resp.raise_for_status()
    our_products = our_resp.json()

    comp_resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/sp_products?select=product_name,market_name,latest_price,product_url&market_name=neq.Bizim Toptan&limit=2000",
        headers=_headers(), timeout=10
    )
    comp_resp.raise_for_status()
    comp_products = comp_resp.json()

    import re
    cheaper = []
    equal = []

    for our in our_products:
        our_name = our.get("product_name", "")
        our_price = our.get("sale_price")
        if not our_price or not our_name:
            continue
        our_price = float(our_price)
        our_qty, our_unit = _extract_unit(our_name)

        our_brand = _extract_brand(our_name)
        best_score = 0
        best_match = None
        for comp in comp_products:
            comp_name = comp.get("product_name", "")
            # Skip bulk/multi-packs from competitors
            if re.search(r'\d+\s*x\s*\d+|\d+\'lü|\d+\'li|\'lü|\'li', comp_name.lower()):
                continue
            # Brand must match (first word)
            if our_brand and _extract_brand(comp_name) != our_brand:
                continue
            score = fuzz.token_sort_ratio(our_name.lower(), comp_name.lower())
            if score <= best_score:
                continue
            # If our product has a unit, competitor must match it
            if our_qty and our_unit:
                comp_qty, comp_unit = _extract_unit(comp_name)
                if not comp_qty or comp_unit != our_unit:
                    continue
                # Allow 10% tolerance in quantity (e.g. 330g vs 360g is ok)
                if abs(our_qty - comp_qty) / our_qty > 0.10:
                    continue
            best_score = score
            best_match = comp

        # Require 80% similarity for reliable matches
        if best_score >= 80 and best_match:
            comp_price_raw = best_match.get("latest_price")
            if not comp_price_raw:
                continue
            try:
                comp_price = float(str(comp_price_raw).replace(",", ".").replace(" TL", "").strip())
            except ValueError:
                continue

            entry = {
                "our_name": our_name,
                "our_price": our_price,
                "comp_name": best_match.get("product_name"),
                "comp_price": comp_price,
                "comp_market": best_match.get("market_name"),
                "comp_url": best_match.get("product_url", ""),
                "match_score": best_score,
            }

            if our_price < comp_price:
                entry["savings"] = round(comp_price - our_price, 2)
                cheaper.append(entry)
            elif abs(our_price - comp_price) < 5.0 and our_price <= comp_price:  # within 5 TL and we are not more expensive
                entry["savings"] = 0
                equal.append(entry)

    cheaper.sort(key=lambda x: x["savings"], reverse=True)
    equal.sort(key=lambda x: x["our_price"], reverse=True)
    return {"cheaper": cheaper[:limit], "equal": equal[:5]}


if __name__ == "__main__":
    print("Testing Supabase connection...")
    products = get_product()
    print(f"Found {len(products)} products")
    print("\nFormatted for AI:")
    print(get_products_text()[:500])
