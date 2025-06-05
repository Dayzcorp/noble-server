import os
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from openai import OpenAI
import requests

load_dotenv()

def get_shopify_products():
    url = "https://8797e8-2.myshopify.com/api/2023-10/graphql.json"
    headers = {
        "X-Shopify-Storefront-Access-Token": "63539e3f3eb73cd8e852353ca9897543",
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
            image = p["node"]["images"]["edges"][0]["node"]["src"] if p["node"]["images"]["edges"] else "No image"
            result += f"Title: {title}\nDescription: {description}\nImage: {image}\n\n"
        return result.strip()
    return "No products found."

app = Flask(__name__, template_folder="templates")

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

@app.route("/", methods=["GET","HEAD"])
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("prompt", "")

    try:
        product_info= get_shopify_products()

        response = client.chat.completions.create(
            model="deepseek/deepseek-chat-v3-0324:free",
            messages=[
                {"role": "system", "content": f"You are Noble, a smart, witty, assistant for a Shopify store. Here is what's in your store:\n{product_info}. You only respond with clear human-like answers, never markdown, code, or GitHub links."},
                {"role": "user", "content": user_input}
            ]
        )

        reply = response.choices[0].message.content
        return jsonify({"response": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)