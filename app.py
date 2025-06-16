import os
from functools import wraps
from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    redirect,
    url_for,
    session,
    abort,
    Response,
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
    """Redirect to billing page if no active plan."""
    if has_active_plan():
        return None
    return redirect(url_for("billing", message="Please select a plan to continue."))


def require_setup():
    """Redirect to setup if chatbot settings are missing."""
    if session.get("bot_name") and session.get("shopify_domain"):
        return None
    return redirect(url_for("setup"))


def require_access(func):
    """Ensure billing and setup have been completed."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not has_active_plan() and not session.get("billing_active"):
            return redirect(url_for("billing"))
        if not session.get("bot_name") or not session.get("shopify_domain"):
            return redirect(url_for("setup"))
        return func(*args, **kwargs)

    return wrapper


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
    if guard:
        return guard

    if session.get("bot_name") and session.get("shopify_domain"):
        return redirect(url_for("index"))

    if request.method == "POST":
        bot_name = request.form.get("bot_name", "").strip()
        domain = request.form.get("shopify_domain", "").strip()
        token = request.form.get("shopify_token", "").strip()
        if not bot_name or not domain:
            cfg = {
                "bot_name": bot_name or DEFAULT_BOT,
                "shopify_domain": domain,
                "shopify_token": token,
            }
            error = "Bot name and Shopify domain are required."
            return render_template("setup.html", error=error, **cfg)

        session["bot_name"] = bot_name
        session["shopify_domain"] = domain
        if token:
            session["shopify_token"] = token

        return render_template(
            "setup.html",
            bot_name=bot_name,
            shopify_domain=domain,
            shopify_token=token,
            success=True,
        )

    cfg = get_config()
    return render_template(
        "setup.html",
        bot_name=cfg["bot_name"],
        shopify_domain=cfg["shopify_domain"],
        shopify_token=cfg["shopify_token"],
        error=None,
    )


@app.route("/")
@require_access
def index() -> str:
    cfg = get_config()
    status = plan_status()
    plan_name = status["name"] if status else ""
    expiry = status.get("expiry") if status else None
    exp_str = expiry.strftime("%Y-%m-%d") if expiry else None
    return render_template(
        "index.html",
        bot_name=cfg["bot_name"],
        shop_domain=cfg["shopify_domain"],
        plan_name=plan_name,
        plan_expiry=exp_str,
        host=request.url_root.rstrip("/"),
    )


@app.route("/chat", methods=["GET"])
def chat_window() -> str:
    """Public chat window shown inside the storefront iframe."""
    cfg = get_config()
    return render_template(
        "chat.html",
        bot_name=cfg["bot_name"],
        shop_domain=cfg["shopify_domain"],
    )


@app.route("/chat", methods=["POST"])
@require_access
def chat() -> tuple:

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


@app.route("/widget.js")
def widget_js() -> Response:
    """Serve the storefront widget script."""
    shop = request.args.get("shop", "")
    host = request.url_root.rstrip("/")
    js = f"""
(function() {{
  if (window.SEEPWidgetLoaded) return; 
  window.SEEPWidgetLoaded = true;
  var bubble = document.createElement('div');
  bubble.id = 'seep-bubble';
  bubble.style.position = 'fixed';
  bubble.style.bottom = '20px';
  bubble.style.right = '20px';
  bubble.style.width = '60px';
  bubble.style.height = '60px';
  bubble.style.borderRadius = '50%';
  bubble.style.background = '#005b96';
  bubble.style.color = '#fff';
  bubble.style.display = 'flex';
  bubble.style.justifyContent = 'center';
  bubble.style.alignItems = 'center';
  bubble.style.cursor = 'pointer';
  bubble.style.boxShadow = '0 2px 6px rgba(0,0,0,0.3)';
  bubble.style.zIndex = '9999';
  bubble.textContent = 'SEEP';

  var panel = document.createElement('div');
  panel.id = 'seep-panel';
  panel.style.position = 'fixed';
  panel.style.bottom = '90px';
  panel.style.right = '20px';
  panel.style.width = '400px';
  panel.style.height = '0';
  panel.style.maxHeight = '500px';
  panel.style.background = '#fff';
  panel.style.borderRadius = '8px';
  panel.style.boxShadow = '0 4px 12px rgba(0,0,0,0.2)';
  panel.style.overflow = 'hidden';
  panel.style.transition = 'height 0.3s ease';
  panel.style.zIndex = '9999';

  var frame = document.createElement('iframe');
  frame.src = '{host}/chat?shop={shop}';
  frame.style.border = 'none';
  frame.style.width = '100%';
  frame.style.height = '100%';
  frame.setAttribute('sandbox', 'allow-scripts allow-same-origin');
  panel.appendChild(frame);

  bubble.addEventListener('click', function() {{
    if (panel.style.height === '0px' || panel.style.height === '') {{
      panel.style.height = '500px';
    }} else {{
      panel.style.height = '0';
    }}
  }});

  document.body.appendChild(bubble);
  document.body.appendChild(panel);
}})();
"""
    return Response(js, mimetype="text/javascript")


# ---------------------------------------------------------------------------
# Dummy billing helpers
# ---------------------------------------------------------------------------

def start_plan(plan_key: str) -> None:
    """Store the selected plan and start date in the session."""
    if plan_key not in BILLING_PLANS:
        return
    now = datetime.utcnow()
    session["plan"] = plan_key
    session["billing_start"] = now.isoformat()
    session.pop("canceled", None)
    session["billing_active"] = True


def months_since(start: str) -> int:
    """Return the whole number of months between start date and now."""
    dt = datetime.fromisoformat(start)
    now = datetime.utcnow()
    return (now.year - dt.year) * 12 + now.month - dt.month


def has_active_plan() -> bool:
    """Check whether the current session has an active plan."""
    plan = session.get("plan")
    start = session.get("billing_start")
    if not plan or not start or session.get("canceled"):
        return False

    info = BILLING_PLANS.get(plan)
    if not info:
        return False

    now = datetime.utcnow()
    start_dt = datetime.fromisoformat(start)

    if plan == "monthly":
        trial_end = start_dt + timedelta(days=info.get("trial_days", 0))
        intro_end = trial_end + timedelta(days=30)
        if now < trial_end:
            return True
        if now < intro_end:
            return True
        # auto-renews indefinitely unless canceled
        return True

    commitment = info.get("commitment", 0)
    if commitment:
        if months_since(start) < commitment:
            return True
        return False

    return False


def plan_status() -> dict | None:
    """Return plan name and expiry date if applicable."""
    plan = session.get("plan")
    start = session.get("billing_start")
    if not plan or not start:
        return None
    info = BILLING_PLANS.get(plan)
    if not info:
        return None

    start_dt = datetime.fromisoformat(start)
    now = datetime.utcnow()

    if plan == "monthly":
        trial_end = start_dt + timedelta(days=info.get("trial_days", 0))
        intro_end = trial_end + timedelta(days=30)
        if now < trial_end:
            return {"name": info["name"], "expiry": trial_end}
        if now < intro_end:
            return {"name": info["name"], "expiry": intro_end}
        return {"name": info["name"], "expiry": None}

    commitment = info.get("commitment", 0)
    if commitment:
        expiry = start_dt + timedelta(days=30 * commitment)
        return {"name": info["name"], "expiry": expiry}

    return {"name": info["name"], "expiry": None}


@app.route("/billing")
def billing() -> str:
    """Render plan selection page."""
    message = request.args.get("message")
    active = has_active_plan()
    current_plan = session.get("plan")
    return render_template(
        "billing_select.html",
        plans=BILLING_PLANS,
        message=message,
        active=active,
        current_plan=current_plan,
    )


@app.route("/select_plan/<plan>", methods=["POST"])
def select_plan(plan: str):
    """Activate the selected plan (dummy billing)."""
    if plan not in BILLING_PLANS:
        return redirect(url_for("billing", message="Invalid plan."))
    start_plan(plan)
    return redirect(url_for("index"))


@app.route("/cancel_plan", methods=["POST"])
def cancel_plan():
    """Attempt to cancel the current subscription."""
    if not has_active_plan():
        return redirect(url_for("billing"))
    plan = session.get("plan")
    info = BILLING_PLANS.get(plan, {})
    start = session.get("billing_start")
    if start and info.get("commitment"):
        months = months_since(start)
        if months < info["commitment"]:
            msg = "This plan cannot be canceled until the commitment period ends."
            return redirect(url_for("billing", message=msg))
    session["canceled"] = True
    for key in ["plan", "billing_start"]:
        session.pop(key, None)
    session.pop("billing_active", None)
    return redirect(url_for("billing", message="Subscription canceled."))





if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
