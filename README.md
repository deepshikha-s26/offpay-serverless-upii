# OffPay – Serverless UPI (Offline Payment Demo)

A college project that shows how a UPI-style payment can be made **without internet**.
The payer's phone signs a payment, hands it to the receiver, and the bank settles it later when someone gets online.

**Tech stack:** Python (Flask, SQLite, `cryptography`) · HTML · CSS · JavaScript (Web Crypto API)

## How it works

1. **Register** – the phone creates an ECDSA key pair. The private key stays on the phone; the public key goes to the bank.
2. **Add money** (online) – bank balance moves into a small *offline wallet* (limit Rs.2000, like UPI Lite).
3. **Pay** (offline) – the phone signs `{from, to, amount, time, tx_id}` and shows a payment code.
4. **Receive** (offline) – the receiver pastes the code; the app verifies the signature locally.
5. **Sync** (online) – the signed payments reach the server, which verifies the signature, rejects duplicates using the unique `tx_id`, checks the wallet balance, and moves the money.

## Run it

```bash
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

### Try the demo
1. Create two accounts (e.g. *Alice* and *Bob*) using the account switcher.
2. As Alice: add Rs.500 to the wallet, switch the top-right toggle to **Offline**.
3. Pay Bob's UPI ID, copy the generated code.
4. Switch to Bob, paste the code in **Receive** (still offline).
5. Turn **Online**, click **Sync now**. Bob's bank balance increases.
6. Paste the same code again and sync – it is rejected as a duplicate.

Run the backend test: `python test_backend.py`

## Project structure
```
offpay/
├── app.py             # Flask server: register, load wallet, sync/settle
├── test_backend.py    # Automated check of settlement and security
├── requirements.txt
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js         # Key generation, signing, verification, offline storage
```

## API
| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/register` | Create account with public key |
| GET | `/api/user/<id>` | Get balances |
| POST | `/api/wallet/load` | Bank balance → offline wallet |
| POST | `/api/sync` | Verify and settle signed payments |

## Limitations (good to mention in your viva)
- Payment codes are copy-pasted; a real system would use QR, Bluetooth or NFC.
- The receiver trusts the public key inside the code. A real system would have the bank certify user keys.
- Private keys sit in browser `localStorage`; real phones use a secure hardware element.
- A payer can only overspend up to their wallet, but the receiver bears the risk until sync.

## Future work
QR/NFC transfer, bank-signed certificates, PIN protection, transaction history from the server.
