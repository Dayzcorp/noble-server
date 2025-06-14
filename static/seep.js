const msgs = document.getElementById("msgs");
const input = document.getElementById("txt");
const spinner = document.getElementById("spinner");

let botName = CONFIG.bot_name || sessionStorage.getItem("bot_name") || "Seep";
let shopifyDomain = CONFIG.shopify_domain || sessionStorage.getItem("shopify_domain") || "";

sessionStorage.setItem("bot_name", botName);
sessionStorage.setItem("shopify_domain", shopifyDomain);

async function send() {
  const text = input.value.trim();
  if (!text) return;

  append("user", text);
  input.value = "";
  spinner.style.display = "block";

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
    const reply = data.reply || data.error || "Sorry, I didn't get that.";
    append("bot", reply);
  } catch (e) {
    append("bot", "Error talking to the server.");
  } finally {
    spinner.style.display = "none";
  }
}

input.addEventListener("keyup", (e) => {
  if (e.key === "Enter") {
    send();
  }
});

window.send = send;

function append(sender, text) {
  const div = document.createElement("div");
  div.className = sender;
  div.textContent = `${sender === "user" ? "You" : botName}: ${text}`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}
