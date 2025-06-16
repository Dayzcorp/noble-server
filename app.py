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
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET", os.urandom(24))

DEFAULT_BOT = os.getenv("BOT_NAME", "SEEP")
DEFAULT_DOMAIN = os.getenv("SHOP_DOMAIN", "example.myshopify.com")
DEFAULT_TOKEN = os.getenv("SHOPIFY_STOREFRONT_TOKEN", "")

# Basic plan definitions for billing. Prices are in USD.
BILLING_PLANS = {
    "monthly": {"price": 14.99, "trial_days": 7, "name": "SEEP Monthly Plan"},
    "3m": {"price": 53.97, "trial_days": 0, "name": "SEEP 3 Month Plan"},
    "6m": {"price": 95.94, "trial_days": 0, "name": "SEEP 6 Month Plan"},
    "12m": {"price": 159.92, "trial_days": 0, "name": "SEEP Annual Plan"},
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
    """Redirect to billing page if no active charge is stored."""
    if session.get("charge_status") == "active":
        return None
    return redirect(url_for("billing_select", message="Please accept billing to continue using SEEP."))


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


def create_shopify_charge(plan_key: str) -> tuple[str, int] | tuple[None, None]:
    """Create a RecurringApplicationCharge and return confirmation URL and id."""
    plan = BILLING_PLANS.get(plan_key)
    cfg = get_config()
    domain = cfg.get("shopify_domain")
    token = cfg.get("shopify_token")
    if not plan or not domain or not token:
        return None, None
    url = (
        f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/recurring_application_charges.json"
    )
    charge = {
        "name": plan["name"],
        "price": plan["price"],
        "trial_days": plan["trial_days"],
        "return_url": url_for("billing_confirm", _external=True),
        "test": True,
    }
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            url, json={"recurring_application_charge": charge}, headers=headers, timeout=10
        )
        data = resp.json().get("recurring_application_charge", {})
        return data.get("confirmation_url"), data.get("id")
    except Exception:
        return None, None


@app.route("/billing/select")
def billing_select() -> str:
    """Render plan selection page."""
    message = request.args.get("message")
    return render_template("billing_select.html", plans=BILLING_PLANS, message=message)


@app.route("/billing/create/<plan>", methods=["POST"])
def billing_create(plan: str):
    """Create a charge for the selected plan and redirect to Shopify."""
    confirmation_url, cid = create_shopify_charge(plan)
    if not confirmation_url:
        return redirect(url_for("billing_select", message="Could not create charge."))
    session["plan"] = plan
    session["charge_id"] = cid
    session["charge_status"] = "pending"
    return redirect(confirmation_url)


@app.route("/billing/confirm")
def billing_confirm() -> str:
    """Activate the charge after the merchant accepts it."""
    charge_id = request.args.get("charge_id") or session.get("charge_id")
    if not charge_id:
        return redirect(url_for("billing_select", message="Missing charge id."))
    cfg = get_config()
    domain = cfg.get("shopify_domain")
    token = cfg.get("shopify_token")
    url = (
        f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/recurring_application_charges/{charge_id}/activate.json"
    )
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            session["charge_status"] = "active"
        else:
            session["charge_status"] = "declined"
    except Exception:
        session["charge_status"] = "declined"
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
