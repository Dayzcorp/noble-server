import os
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET", os.urandom(24))

DEFAULT_BOT = os.getenv("BOT_NAME", "SEEP")
DEFAULT_DOMAIN = os.getenv("SHOP_DOMAIN", "example.myshopify.com")
DEFAULT_TOKEN = os.getenv("SHOPIFY_STOREFRONT_TOKEN", "")


def get_config() -> dict:
    """Return current chatbot configuration."""
    return {
        "bot_name": session.get("bot_name", DEFAULT_BOT),
        "shopify_domain": session.get("shopify_domain", DEFAULT_DOMAIN),
        "shopify_token": session.get("shopify_token", DEFAULT_TOKEN),
    }


client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
    http_client=None  # Use default client, remove 'proxies'
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
    cfg = get_config()
    return render_template("index.html", bot_name=cfg["bot_name"], shop_domain=cfg["shopify_domain"])


@app.route("/chat", methods=["POST"])
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
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_input},
            ],
        )
        print("AI response raw:", resp)  # <-- NEW LINE
        reply = resp.choices[0].message.content
        return jsonify({"reply": reply})
    except Exception as e:
        print("Error during chat:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
