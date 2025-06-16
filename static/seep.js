const msgs = document.getElementById('msgs');
const input = document.getElementById('txt');
const spinner = document.getElementById('spinner');

let botName = sessionStorage.getItem('bot_name') || CONFIG.bot_name || 'SEEP';
let shopifyDomain = sessionStorage.getItem('shopify_domain') || CONFIG.shopify_domain || 'example.myshopify.com';
let shopifyToken = sessionStorage.getItem('shopify_token') || '';

sessionStorage.setItem('bot_name', botName);
sessionStorage.setItem('shopify_domain', shopifyDomain);
if (shopifyToken) sessionStorage.setItem('shopify_token', shopifyToken);

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
        prompt: text
      })
    });

    const data = await res.json();
    if (data.error || !data.reply) {
      throw new Error("server");
    }
    append("bot", data.reply);
  } catch (e) {
    append("bot", "SEEP is sleeping...");
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
  const wrapper = document.createElement('div');
  wrapper.className = sender;
  const message = document.createElement('div');
  message.className = 'message-text';
  const time = document.createElement('span');
  time.className = 'timestamp';
  time.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  wrapper.appendChild(message);
  wrapper.appendChild(time);
  msgs.appendChild(wrapper);
  msgs.scrollTop = msgs.scrollHeight;

  if (sender === 'bot') {
    message.textContent = botName + ': ';
    const clean = text.replace(/[\*_`]/g, '');
    typeText(message, clean);
  } else {
    message.textContent = 'You: ' + text;
  }
}

function typeText(el, text) {
  let i = 0;
  (function tick() {
    if (i < text.length) {
      el.textContent += text.charAt(i);
      i++;
      setTimeout(tick, 20);
    }
  })();
}
