import os
from flask import Flask, request, jsonify, render_template, url_for
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

def get_shopify_products():
    import os
    import requests

    shop_domain = os.getenv("SHOP_DOMAIN")
    storefront_token = os.getenv("SHOPIFY_STOREFRONT_TOKEN")
    url = f"https://{shop_domain}/api/2023-10/graphql.json"

    headers = {
        "X-Shopify-Storefront-Access-Token": storefront_token,
        "Content-Type": "application/json"
    }

    query = """
    {
      products(first: 5) {
        edges {
          node {
            title
            description
            images(first: 1) {
              edges {
                node {
                  src
                }
              }
            }
          }
        }
      }
    }
    """

    response = requests.post(url, json={"query": query}, headers=headers)
    data = response.json()

    if "data" in data:
        products = data["data"]["products"]["edges"]
        result = ""
        for p in products:
            title = p["node"]["title"]
            description = p["node"]["description"]
            image = (
                p["node"]["images"]["edges"][0]["node"]["src"]
                if p["node"]["images"]["edges"]
                else "No image"
            )
            result += f"Title: {title}\nDescription: {description}\nImage: {image}\n\n"
        return result.strip()
    return "No products found."

app = Flask(__name__, template_folder="templates")
client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

@app.route("/", methods=["GET", "HEAD"])
def home():
    return render_template(
        "index.html",
        bot_name=os.getenv("BOT_NAME", "Seep")
    )

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_input = data.get("prompt", "")
    shop_domain = data.get("shop_domain", "")
    bot_name = os.getenv("BOT_NAME", "Seep")

    try:
        # Fetch products using the shop domain provided
        product_info = get_shopify_products(shop_domain)

        system_msg = f"You are {bot_name}, a smart, witty assistant for a Shopify store. Here's what's in the store:\n{product_info}\n\nAnswer in clear, human-like text with no markdown, code, or links."

        response = client.chat.completions.create(
            model="deepseek/deepseek-chat-v3-0324:free",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_input}
            ]
        )

        reply = response.choices[0].message.content
        return jsonify({"reply": reply})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # In-memory config (will reset every server restart)
user_config = {
        "bot_name": "Seep",
        "shopify_domain": "",
        "shopify_token": ""
    }

@app.route("/setup", methods=["GET", "POST"])
    def setup():
        if request.method == "POST":
            user_config["bot_name"] = request.form.get("bot_name", "Seep")
            user_config["shopify_domain"] = request.form.get("shopify_domain", "")
            user_config["shopify_token"] = request.form.get("shopify_token", "")
            return redirect(url_for("index"))
        return render_template("setup.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))