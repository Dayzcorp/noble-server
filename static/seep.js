const msgs = document.getElementById("msgs");
const botName = CONFIG.bot_name;
const shopifyDomain = CONFIG.shopify_domain;

async function send() {
  const input = document.getElementById("txt");
  const text = input.value.trim();
  if (!text) return;

  append("user", text);
  input.value = "";

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        prompt: text,
        shop_domain: shopifyDomain
      })
    });

    const data = await res.json();
    const reply = data.reply || "Sorry, I didn't get that.";
    append("bot", reply);
  } catch (e) {
    append("bot", "Error talking to the server.");
  }
}

function append(sender, text) {
  const div = document.createElement("div");
  div.className = sender;
  div.textContent = `${sender === "user" ? "You" : botName}: ${text}`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

