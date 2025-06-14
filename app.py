import os
from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    redirect,
    url_for,
)
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = Flask(__name__, template_folder="templates")

# Configuration stored in memory so store owners can provide values
user_config = {
    "bot_name": os.getenv("BOT_NAME", "Seep"),
    "shopify_domain": os.getenv("SHOP_DOMAIN", ""),
    "shopify_token": os.getenv("SHOPIFY_STOREFRONT_TOKEN", ""),
}

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)


def get_shopify_products(domain: str | None = None, token: str | None = None) -> str:
    """Fetch a few products from Shopify. Return human-readable summary."""
    shop_domain = domain or user_config.get("shopify_domain")
    storefront_token = token or user_config.get("shopify_token")
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
        result.append(
            f"Title: {title}\nDescription: {description}\nImage: {image}"
        )
    return "\n\n".join(result)


@app.route("/health", methods=["GET"])
def health() -> tuple[str, int]:
    return "OK", 200


@app.route("/", methods=["GET", "POST"])
def setup():
    if request.method == "POST":
        user_config["bot_name"] = request.form.get("bot_name", user_config["bot_name"])
        user_config["shopify_domain"] = request.form.get("shopify_domain", user_config["shopify_domain"])
        token = request.form.get("shopify_token")
        if token:
            user_config["shopify_token"] = token
        return redirect(url_for("chat", bot_name=user_config["bot_name"], shop_domain=user_config["shopify_domain"]))

    return render_template(
        "setup.html",
        bot_name=user_config["bot_name"],
        shopify_domain=user_config["shopify_domain"],
        shopify_token=user_config["shopify_token"],
    )


@app.route("/chat", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        data = request.get_json(force=True)
        user_input = data.get("prompt", "")
        shop_domain = data.get("shop_domain") or user_config.get("shopify_domain")
        bot_name = user_config.get("bot_name", "Seep")
        token = user_config.get("shopify_token")

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
            return jsonify({"reply": reply})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # GET request: render UI
    bot_name = request.args.get("bot_name") or user_config.get("bot_name", "Seep")
    shop_domain = request.args.get("shop_domain") or user_config.get("shopify_domain", "")
    return render_template("index.html", bot_name=bot_name, shop_domain=shop_domain)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
