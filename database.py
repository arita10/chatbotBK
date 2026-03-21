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


if __name__ == "__main__":
    print("Testing Supabase connection...")
    products = get_product()
    print(f"Found {len(products)} products")
    print("\nFormatted for AI:")
    print(get_products_text()[:500])
