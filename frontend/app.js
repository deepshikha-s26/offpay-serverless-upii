// OffPay frontend. Everything about the "phone" lives here.
// Keys and payments are stored in localStorage, so the app keeps working offline.

const ALGO = { name: "ECDSA", namedCurve: "P-256" };
const SIGN = { name: "ECDSA", hash: "SHA-256" };

const $ = (id) => document.getElementById(id);
let online = true;
let state = JSON.parse(localStorage.getItem("offpay") || '{"accounts":{},"current":null}');

const save = () => localStorage.setItem("offpay", JSON.stringify(state));
const me = () => state.accounts[state.current];
const toB64 = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes)));
const fromB64 = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));

function toast(message, isError = false) {
  const box = $("toast");
  box.textContent = message;
  box.className = isError ? "error" : "";
  box.hidden = false;
  setTimeout(() => (box.hidden = true), 3000);
}

// Talk to the Python server. Fails on purpose when the switch is "Offline".
async function api(path, body) {
  if (!online) throw new Error("You are offline. Turn the switch on first.");
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Server error");
  return data;
}

// Run a button action and show any error as a toast.
function action(fn) {
  return async () => {
    try { await fn(); } catch (err) { toast(err.message, true); }
    render();
  };
}

// ---------- Account ----------
async function createAccount() {
  const name = $("newName").value.trim();
  if (!name) throw new Error("Enter your name.");

  // The private key is created on the phone and never leaves it.
  const keys = await crypto.subtle.generateKey(ALGO, true, ["sign", "verify"]);
  const publicKey = toB64(await crypto.subtle.exportKey("raw", keys.publicKey));
  const privateJwk = await crypto.subtle.exportKey("jwk", keys.privateKey);

  const data = await api("/api/register", { name, public_key: publicKey });
  state.accounts[data.id] = { id: data.id, name, publicKey, privateJwk, bank: data.balance, wallet: 0, queue: [], history: [] };
  state.current = data.id;
  $("newName").value = "";
  toast("Account created: " + data.id);
}

async function loadWallet() {
  const amount = parseInt($("loadAmount").value);
  const data = await api("/api/wallet/load", { user_id: me().id, amount });
  me().bank = data.balance;
  me().wallet += amount;
  $("loadAmount").value = "";
  toast("Money added to offline wallet.");
}

// ---------- Pay (offline) ----------
async function pay() {
  const to = $("payTo").value.trim();
  const amount = parseInt($("payAmount").value);
  if (!to || to === me().id) throw new Error("Enter a valid receiver ID.");
  if (!(amount > 0)) throw new Error("Enter a valid amount.");
  if (amount > me().wallet) throw new Error("Not enough money in offline wallet.");

  // 1. Describe the payment, 2. sign it with our private key.
  const tx = { amount, from: me().id, time: Date.now(), to, tx_id: crypto.randomUUID() };
  const message = JSON.stringify(tx);
  const privateKey = await crypto.subtle.importKey("jwk", me().privateJwk, ALGO, false, ["sign"]);
  const signature = await crypto.subtle.sign(SIGN, privateKey, new TextEncoder().encode(message));

  const token = { message, signature: toB64(signature), sender_pub: me().publicKey };
  me().wallet -= amount;
  me().queue.push(token);
  me().history.unshift({ tx_id: tx.tx_id, type: "Sent", other: to, amount, status: "pending" });
  $("tokenOut").value = btoa(JSON.stringify(token));
  toast("Payment code created. Give it to the receiver.");
}

// ---------- Receive (offline) ----------
async function receive() {
  let token, tx;
  try {
    token = JSON.parse(atob($("tokenIn").value.trim()));
    tx = JSON.parse(token.message);
  } catch {
    throw new Error("This is not a valid payment code.");
  }
  if (tx.to !== me().id) throw new Error("This payment is not for you.");
  if (me().history.some((h) => h.tx_id === tx.tx_id)) throw new Error("Payment already received.");

  // Check the signature using the sender's public key (no internet needed).
  const publicKey = await crypto.subtle.importKey("raw", fromB64(token.sender_pub), ALGO, false, ["verify"]);
  const valid = await crypto.subtle.verify(SIGN, publicKey, fromB64(token.signature), new TextEncoder().encode(token.message));
  if (!valid) throw new Error("Signature is invalid. Payment rejected.");

  me().queue.push(token);
  me().history.unshift({ tx_id: tx.tx_id, type: "Received", other: tx.from, amount: tx.amount, status: "pending" });
  $("tokenIn").value = "";
  toast(`Rs.${tx.amount} received. Sync when online to get it in the bank.`);
}

// ---------- Sync (online) ----------
async function sync() {
  if (!me().queue.length) throw new Error("Nothing to sync.");
  const { results } = await api("/api/sync", { tokens: me().queue });

  for (const result of results) {
    const item = me().history.find((h) => h.tx_id === result.tx_id);
    if (item) item.status = result.status;
  }
  me().queue = [];

  const user = await api("/api/user/" + encodeURIComponent(me().id));
  me().bank = user.balance;
  me().wallet = user.wallet;
  toast("Sync complete.");
}

// ---------- Drawing the screen ----------
function render() {
  const accounts = Object.values(state.accounts);
  const select = $("accountSelect");
  select.replaceChildren(...accounts.map((a) => new Option(`${a.name} (${a.id})`, a.id, false, a.id === state.current)));
  $("switchRow").hidden = accounts.length === 0;
  $("app").hidden = !me();

  if (me()) {
    $("upiId").textContent = me().id;
    $("bankBal").textContent = "Rs." + me().bank;
    $("walletBal").textContent = "Rs." + me().wallet;
    $("queueCount").textContent = me().queue.length;
    $("history").replaceChildren(...me().history.map((h) => {
      const row = document.createElement("tr");
      [h.type, h.other, "Rs." + h.amount, h.status].forEach((text) => {
        const cell = document.createElement("td");
        cell.textContent = text;
        row.append(cell);
      });
      return row;
    }));
  }
  save();
}

// ---------- Wire up buttons ----------
$("createBtn").onclick = action(createAccount);
$("loadBtn").onclick = action(loadWallet);
$("payBtn").onclick = action(pay);
$("receiveBtn").onclick = action(receive);
$("syncBtn").onclick = action(sync);
$("accountSelect").onchange = (e) => { state.current = e.target.value; render(); };
$("onlineSwitch").onchange = (e) => {
  online = e.target.checked;
  $("netLabel").textContent = online ? "Online" : "Offline";
  document.body.classList.toggle("offline", !online);
};

render();
