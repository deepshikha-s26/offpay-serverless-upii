"""
OffPay - a "serverless UPI" demo (backend).

Idea: payments are signed on the phone and handed to the receiver WITHOUT internet.
Later, when someone is online, the signed payments are sent here (/api/sync).
This server checks every signature, blocks double spending, and settles the money.
"""
import base64
import json
import os
import random
import sqlite3
import string

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from flask import Flask, g, jsonify, request

DB_FILE = os.environ.get("OFFPAY_DB", "offpay.db")
START_BALANCE = 10000   # demo money given to every new user (Rs.)
WALLET_LIMIT = 2000     # max money allowed in the offline wallet (like UPI Lite)

app = Flask(__name__, static_folder="frontend", static_url_path="")


# ---------- Database helpers ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_FILE) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                public_key TEXT NOT NULL,
                balance INTEGER NOT NULL,   -- normal bank balance
                wallet INTEGER NOT NULL     -- offline wallet balance
            );
            CREATE TABLE IF NOT EXISTS transactions (
                tx_id TEXT PRIMARY KEY,     -- unique id = protects from double spending
                sender TEXT NOT NULL,
                receiver TEXT NOT NULL,
                amount INTEGER NOT NULL
            );
            """
        )


# ---------- Cryptography ----------
def load_public_key(public_key_b64):
    """Turn the base64 public key sent by the browser into a key object."""
    raw = base64.b64decode(public_key_b64)
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)


def signature_is_valid(public_key_b64, message, signature_b64):
    """Check that `message` was really signed by the owner of the public key."""
    try:
        public_key = load_public_key(public_key_b64)
        raw = base64.b64decode(signature_b64)
        # The browser gives r||s (64 bytes); the library wants DER format.
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        public_key.verify(der, message.encode(), ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


# ---------- Settlement logic ----------
def settle(db, token):
    """Verify one signed payment and move the money. Returns (tx_id, status)."""
    try:
        tx = json.loads(token["message"])
        tx_id, amount = tx["tx_id"], int(tx["amount"])
    except (KeyError, ValueError, TypeError):
        return None, "rejected: malformed"

    sender = db.execute("SELECT * FROM users WHERE id = ?", (tx.get("from"),)).fetchone()
    receiver = db.execute("SELECT * FROM users WHERE id = ?", (tx.get("to"),)).fetchone()

    if sender is None or receiver is None or sender["id"] == receiver["id"]:
        return tx_id, "rejected: unknown user"
    if amount <= 0:
        return tx_id, "rejected: invalid amount"
    if not signature_is_valid(sender["public_key"], token["message"], token.get("signature", "")):
        return tx_id, "rejected: bad signature"
    if db.execute("SELECT 1 FROM transactions WHERE tx_id = ?", (tx_id,)).fetchone():
        return tx_id, "duplicate"
    if sender["wallet"] < amount:
        return tx_id, "rejected: insufficient wallet"

    db.execute("UPDATE users SET wallet = wallet - ? WHERE id = ?", (amount, sender["id"]))
    db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, receiver["id"]))
    db.execute("INSERT INTO transactions VALUES (?, ?, ?, ?)", (tx_id, sender["id"], receiver["id"], amount))
    return tx_id, "settled"


# ---------- API routes ----------
def error(message, code=400):
    return jsonify({"error": message}), code


@app.route("/")
def home():
    return app.send_static_file("index.html")


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    public_key = data.get("public_key", "")
    if not name or len(name) > 30:
        return error("Enter a name (max 30 characters).")
    try:
        load_public_key(public_key)
    except (ValueError, TypeError):
        return error("Invalid public key.")

    db = get_db()
    while True:  # make a unique UPI id like "alice482@offpay"
        suffix = "".join(random.choices(string.digits, k=3))
        user_id = "".join(c for c in name.lower() if c.isalnum()) + suffix + "@offpay"
        if not db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            break
    db.execute("INSERT INTO users VALUES (?, ?, ?, ?, 0)", (user_id, name, public_key, START_BALANCE))
    db.commit()
    return jsonify({"id": user_id, "balance": START_BALANCE})


@app.route("/api/user/<user_id>")
def get_user(user_id):
    user = get_db().execute("SELECT id, name, balance, wallet FROM users WHERE id = ?", (user_id,)).fetchone()
    return jsonify(dict(user)) if user else error("User not found.", 404)


@app.route("/api/wallet/load", methods=["POST"])
def load_wallet():
    """Move money from the bank balance into the offline wallet (needs internet)."""
    data = request.get_json(silent=True) or {}
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (data.get("user_id"),)).fetchone()
    try:
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        return error("Enter a valid amount.")
    if user is None:
        return error("User not found.", 404)
    if amount <= 0:
        return error("Amount must be positive.")
    if amount > user["balance"]:
        return error("Not enough bank balance.")
    if user["wallet"] + amount > WALLET_LIMIT:
        return error(f"Offline wallet limit is Rs.{WALLET_LIMIT}.")

    db.execute("UPDATE users SET balance = balance - ?, wallet = wallet + ? WHERE id = ?", (amount, amount, user["id"]))
    db.commit()
    return jsonify({"balance": user["balance"] - amount, "wallet": user["wallet"] + amount})


@app.route("/api/sync", methods=["POST"])
def sync():
    """Receive signed offline payments and settle them."""
    tokens = (request.get_json(silent=True) or {}).get("tokens", [])
    db = get_db()
    results = []
    for token in tokens:
        tx_id, status = settle(db, token)
        results.append({"tx_id": tx_id, "status": status})
    db.commit()
    return jsonify({"results": results})


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
