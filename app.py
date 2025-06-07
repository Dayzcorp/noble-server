import os
import requests
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = Flask(__name__, template_folder="templates")

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

def get_shopify_products():
    url = "https://8797e8-2.myshopify.com/api/2023-10/graphql.json"
    headers = {
        "X-Shopify-Storefront-Access-Token": os.getenv("SHOPIFY_STOREFRONT_TOKEN"),
        "Content-Type": "application/json"
    }
    query = """
    {
      products(first: 10) {
        edges {
          node {
            title
            description
            images(first:1) { edges { node { src } } }
            priceRange { minVariantPrice { amount currencyCode } }
          }
        }
      }
    }
    """
    resp = requests.post(url, json={"query": query}, headers=headers)
    data = resp.json()
    edges = data.get("data", {}).get("products", {}).get("edges", [])
    out = []
    for edge in edges:
        n = edge["node"]
        out.append(
            f"- {n['title']}: {n['description'][:60]}… "
            f"({n['priceRange']['minVariantPrice']['amount']} {n['priceRange']['minVariantPrice']['currencyCode']})"
        )
    return "\n".join(out) if out else "No products found."

@app.route("/", methods=["GET"])
def home():
    bot_name = request.args.get("bot_name", "Seep")
    return render_template("index.html", bot_name=bot_name)

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("prompt", "")
    bot_name   = request.args.get("bot_name", "Seep")
    store_info = get_shopify_products()

    try:
        system_prompt = (
            f"You are {bot_name}, a friendly shop assistant. "
            f"Here’s what’s in the store:\n{store_info}\n"
            f"Answer clearly, no code or markdown."
        )
        response = client.chat.completions.create(
            model="deepseek/deepseek-chat-v3-0324:free",
            messages=[
                {"role":"system", "content": system_prompt},
                {"role":"user",   "content": user_input}
            ]
        )
        reply = response.choices[0].message.content
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))