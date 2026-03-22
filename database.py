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
        headers=_headers(),
        json=data,
        timeout=10,
    )
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
        headers=_headers(),
        json=data,
        timeout=10,
    )
    response.raise_for_status()


def record_visit():
    # Upsert today's visit count using Supabase REST API
    # First try to increment, if no row exists insert one
    requests.post(
        f"{SUPABASE_URL}/rest/v1/ch_chatbot_visits",
        headers={**_headers(), "Prefer": "resolution=merge-duplicates"},
        json={"visit_date": "now()", "count": 1},
        timeout=10,
    )


def get_cheaper_products(limit=10):
    """
    Compare ch_products with sp_products using fuzzy name matching.
    Returns only products where Balci Market is cheaper than competitors.
    """
    from rapidfuzz import fuzz

    # Fetch our products
    our_resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/ch_products?select=product_name,sale_price",
        headers=_headers(), timeout=10
    )
    our_resp.raise_for_status()
    our_products = our_resp.json()

    # Fetch competitor products
    comp_resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/sp_products?select=product_name,market_name,latest_price&limit=2000",
        headers=_headers(), timeout=10
    )
    comp_resp.raise_for_status()
    comp_products = comp_resp.json()

    cheaper = []

    for our in our_products:
        our_name = our.get("product_name", "")
        our_price = our.get("sale_price")
        if not our_price or not our_name:
            continue
        our_price = float(our_price)

        # Find best fuzzy match in competitor products
        best_score = 0
        best_match = None
        for comp in comp_products:
            comp_name = comp.get("product_name", "")
            score = fuzz.token_sort_ratio(our_name.lower(), comp_name.lower())
            if score > best_score:
                best_score = score
                best_match = comp

        # Only consider matches above 60% similarity
        if best_score >= 60 and best_match:
            comp_price_raw = best_match.get("latest_price")
            if not comp_price_raw:
                continue
            # Clean price string like "89,90" → 89.90
            try:
                comp_price = float(str(comp_price_raw).replace(",", ".").replace(" TL", "").strip())
            except ValueError:
                continue

            # Only add if our price is cheaper
            if our_price < comp_price:
                cheaper.append({
                    "our_name": our_name,
                    "our_price": our_price,
                    "comp_name": best_match.get("product_name"),
                    "comp_price": comp_price,
                    "comp_market": best_match.get("market_name"),
                    "savings": round(comp_price - our_price, 2),
                    "match_score": best_score,
                })

    # Sort by biggest savings first, return top N
    cheaper.sort(key=lambda x: x["savings"], reverse=True)
    return cheaper[:limit]


if __name__ == "__main__":
    print("Testing Supabase connection...")
    products = get_product()
    print(f"Found {len(products)} products")
    print("\nFormatted for AI:")
    print(get_products_text()[:500])
