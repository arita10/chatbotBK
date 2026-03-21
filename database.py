import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Single shared engine — created once at startup, reused by all requests
# pool_size=3: max 3 persistent connections kept open
# max_overflow=2: allow 2 extra connections under heavy load (total max 5)
# pool_timeout=30: wait up to 30s for a free connection before erroring
# pool_recycle=1800: recycle connections every 30min to avoid Aiven idle timeout
_engine = None

def get_engine():
    global _engine
    if _engine is None:
        db_url = os.getenv("DATABASE_URL")
        # Aiven gives 'postgres://...' but SQLAlchemy needs 'postgresql://...'
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        # Detect if using PgBouncer (port 6543) — it doesn't support pre_ping
        is_pgbouncer = ":6543/" in db_url
        _engine = create_engine(
            db_url,
            pool_pre_ping=not is_pgbouncer,  # disable for PgBouncer
            pool_size=3,
            max_overflow=2,
            pool_timeout=30,
            pool_recycle=1800,
        )
    return _engine

def get_product():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM ch_products"))
        columns = result.keys()
        products = [dict(zip(columns, row)) for row in result]
    return products


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
    engine = get_engine()
    
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO chatbot_orders (customer_name, phone, house_no, product, quantity, slip_filename)
            VALUES (:name, :phone, :house_no, :product, :quantity, :slip)
        """), {"name": customer_name, "phone": phone, "house_no": house_no,
               "product": product, "quantity": quantity, "slip": slip_filename})
        
        conn.commit()


def save_feedback(feedback_type, message, user_name="", user_phone="", session_id=""):
    engine = get_engine()
    
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO chatbot_feedback (feedback_type, message, user_name, user_phone, session_id)
            VALUES (:type, :message, :user_name, :user_phone, :session_id)
        """), {"type": feedback_type, "message": message, 
               "user_name": user_name, "user_phone": user_phone, 
               "session_id": session_id})
        
        conn.commit()


def record_visit():
    """
    Called once when a user opens the chatbot.
    Adds 1 to today's visit count.
    If today has no row yet, it creates one starting at 1.
    """
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO chatbot_visits (visit_date, count)
            VALUES (CURRENT_DATE, 1)
            ON CONFLICT (visit_date)
            DO UPDATE SET count = chatbot_visits.count + 1
        """))
        conn.commit()


if __name__ == "__main__":
    print("Testing database connection...")
    products = get_product()
    print(f"Found {len(products)} products")
    print("\nFormatted for AI:")
    print(get_products_text())