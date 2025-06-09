import os
from flask import Flask, request, jsonify, render_template
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

def get_shopify_products():
    url = f"https://{os.getenv('SHOP_DOMAIN')}/api/2023-10/graphql.json"
    headers = {
        "X-Shopify-Storefront-Access-Token": os.getenv("SHOPIFY_STOREFRONT_TOKEN"),
        "Content-Type": "application/json",
    }
    query = """
    {
      products(first: 10) {
        edges {
          node {
            title
            description
            images(first: 1) {
              edges { node { src } }
            }
          }
        }
      }
    }
    """
    resp = requests.post(url, json={"query": query}, headers=headers)
    data = resp.json()
    if "data" in data:
        out = []
        for edge in data["data"]["products"]["edges"]:
            n = edge["node"]
            img = n["images"]["edges"][0]["node"]["src"] if n["images"]["edges"] else ""
            out.append(f"{n['title']} — {n['description']}\nImage: {img}")
        return "\n\n".join(out)
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
    user_input   = request.json.get("prompt", "")
    product_info = get_shopify_products()

    system_msg = (
        f"You are {os.getenv('BOT_NAME','Seep')}, a smart, witty assistant for a Shopify store.\n"
        "Here’s what’s in the store right now:\n"
        f"{product_info}\n\n"
        "Only answer in clear, human-like text—no markdown (write nothing in bold), no code blocks."
    )

    try:
        r = client.chat.completions.create(
            model="deepseek/deepseek-chat-v3-0324:free",
            messages=[
                {"role":"system", "content":system_msg},
                {"role":"user",   "content":user_input}
            ]
        )
        return jsonify({"reply": r.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))