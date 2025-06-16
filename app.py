import os
from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    redirect,
    url_for,
    session,
    abort,
)
import requests
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET", os.urandom(24))

DEFAULT_BOT = os.getenv("BOT_NAME", "SEEP")
DEFAULT_DOMAIN = os.getenv("SHOP_DOMAIN", "example.myshopify.com")
DEFAULT_TOKEN = os.getenv("SHOPIFY_STOREFRONT_TOKEN", "")

# Billing plan metadata for the dummy billing system. Prices are monthly.
BILLING_PLANS = {
    # 7 day trial, then $14.99 for the first 30 days, auto renew $19.99
    "monthly": {
        "name": "Free Trial + Monthly",
        "monthly_price": 19.99,
        "intro_price": 14.99,
        "trial_days": 7,
        "commitment": 0,
    },
    "3m": {
        "name": "3-Month Commitment",
        "monthly_price": 17.99,
        "trial_days": 0,
        "commitment": 3,
    },
    "6m": {
        "name": "6-Month Commitment",
        "monthly_price": 15.99,
        "trial_days": 0,
        "commitment": 6,
    },
    "12m": {
        "name": "1-Year Commitment",
        "monthly_price": 13.33,
        "trial_days": 0,
        "commitment": 12,
    },
}

SHOPIFY_API_VERSION = "2023-10"


def get_config() -> dict:
    """Return current chatbot configuration."""
    return {
        "bot_name": session.get("bot_name", DEFAULT_BOT),
        "shopify_domain": session.get("shopify_domain", DEFAULT_DOMAIN),
        "shopify_token": session.get("shopify_token", DEFAULT_TOKEN),
    }


def require_billing():
    """Redirect to billing page if no active subscription is stored."""
    if session.get("subscription_active"):
        return None
    return redirect(
        url_for("billing_select", message="Please subscribe to continue using SEEP.")
    )


# Initialize OpenAI client for OpenRouter. The modern SDK (>=1.76.2) no longer
# accepts a `proxies` argument, so none is provided here.
client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)


def get_shopify_products(domain: str | None = None, token: str | None = None) -> str:
    """Fetch a few products from Shopify and return a human readable summary."""
    cfg = get_config()
    shop_domain = domain or cfg.get("shopify_domain")
    storefront_token = token or cfg.get("shopify_token")

    if not shop_domain or not storefront_token:
        return "Store info not configured."

    url = f"https://{shop_domain}/api/2023-10/graphql.json"
    headers = {
        "X-Shopify-Storefront-Access-Token": storefront_token,
        "Content-Type": "application/json",
    }
    query = """
    {
      products(first: 5) {
        edges {
          node {
            title
            description
            images(first: 1) { edges { node { src } } }
          }
        }
      }
    }
    """
    try:
        resp = requests.post(url, json={"query": query}, headers=headers, timeout=10)
        data = resp.json()
    except Exception:
        return "Could not fetch products."

    products = data.get("data", {}).get("products", {}).get("edges", [])
    if not products:
        return "No products found."

    result = []
    for p in products:
        node = p.get("node", {})
        title = node.get("title", "")
        description = node.get("description", "")
        images = node.get("images", {}).get("edges", [])
        image = images[0]["node"].get("src") if images else "No image"
        result.append(f"Title: {title}\nDescription: {description}\nImage: {image}")
    return "\n\n".join(result)


@app.route("/health", methods=["GET"])
def health() -> tuple[str, int]:
    return "OK", 200


@app.route("/setup", methods=["GET", "POST"])
def setup() -> str:
    guard = require_billing()
    if guard and request.method != "POST":
        # Allow first-time setup without billing
        cfg = get_config()
        if not cfg.get("shopify_domain") or not cfg.get("shopify_token"):
            guard = None
    if guard:
        return guard

    cfg = get_config()
    if request.method == "POST":
        session["bot_name"] = request.form.get("bot_name", DEFAULT_BOT)
        session["shopify_domain"] = request.form.get("shopify_domain", DEFAULT_DOMAIN)
        token = request.form.get("shopify_token")
        if token:
            session["shopify_token"] = token
        return redirect(url_for("index"))

    return render_template(
        "setup.html",
        bot_name=cfg["bot_name"],
        shopify_domain=cfg["shopify_domain"],
        shopify_token=cfg["shopify_token"],
    )


@app.route("/")
def index() -> str:
    guard = require_billing()
    if guard:
        return guard
    cfg = get_config()
    return render_template("index.html", bot_name=cfg["bot_name"], shop_domain=cfg["shopify_domain"])


@app.route("/chat", methods=["POST"])
def chat() -> tuple:
    guard = require_billing()
    if guard:
        return guard

    data = request.get_json(force=True)
    user_input = data.get("prompt", "")
    cfg = get_config()
    shop_domain = cfg.get("shopify_domain")
    bot_name = cfg.get("bot_name")
    token = cfg.get("shopify_token")

    if user_input.strip().lower() == "/products":
        return jsonify({"reply": get_shopify_products(shop_domain, token)})

    product_info = get_shopify_products(shop_domain, token)
    system_msg = (
        f"You are {bot_name}, a smart, witty assistant for a Shopify store. "
        f"Here's what's in the store:\n{product_info}\n\n"
        "Answer in clear, human-like text with no markdown, code, or links."
    )
    try:
        resp = client.chat.completions.create(
            model="deepseek/deepseek-chat-v3-0324:free",
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_input}],
        )
        reply = resp.choices[0].message.content
        clean = re.sub(r"[\*_`]", "", reply)
        return jsonify({"reply": clean})
    except Exception:
        return jsonify({"error": "server_error"}), 500


# ---------------------------------------------------------------------------
# Dummy billing helpers
# ---------------------------------------------------------------------------

def start_subscription(plan_key: str) -> None:
    """Activate a subscription in the user's session."""
    plan = BILLING_PLANS.get(plan_key)
    if not plan:
        return
    now = datetime.utcnow()
    session["subscription_type"] = plan_key
    session["subscription_active"] = True
    session["subscription_start"] = now.isoformat()
    session["commitment_months"] = plan.get("commitment", 0)
    trial_days = plan.get("trial_days", 0)
    if trial_days:
        session["trial_end"] = (now + timedelta(days=trial_days)).isoformat()
    else:
        session.pop("trial_end", None)


def months_since(start: str) -> int:
    dt = datetime.fromisoformat(start)
    now = datetime.utcnow()
    return (now.year - dt.year) * 12 + now.month - dt.month


@app.route("/billing/select")
def billing_select() -> str:
    """Render plan selection page."""
    message = request.args.get("message")
    active = session.get("subscription_active")
    current_plan = session.get("subscription_type")
    return render_template(
        "billing_select.html",
        plans=BILLING_PLANS,
        message=message,
        active=active,
        current_plan=current_plan,
    )


@app.route("/billing/subscribe/<plan>", methods=["POST"])
def billing_subscribe(plan: str):
    """Activate the selected plan (dummy billing)."""
    if plan not in BILLING_PLANS:
        return redirect(url_for("billing_select", message="Invalid plan."))
    start_subscription(plan)
    return redirect(url_for("index"))


@app.route("/billing/cancel", methods=["POST"])
def billing_cancel():
    """Attempt to cancel the current subscription."""
    if not session.get("subscription_active"):
        return redirect(url_for("billing_select"))
    plan = session.get("subscription_type")
    info = BILLING_PLANS.get(plan, {})
    start = session.get("subscription_start")
    if start and info.get("commitment"):
        months = months_since(start)
        if months < info["commitment"]:
            msg = "This plan cannot be canceled until the commitment period ends."
            return redirect(url_for("billing_select", message=msg))
    for key in [
        "subscription_active",
        "subscription_type",
        "subscription_start",
        "commitment_months",
        "trial_end",
    ]:
        session.pop(key, None)
    return redirect(url_for("billing_select", message="Subscription canceled."))





if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
