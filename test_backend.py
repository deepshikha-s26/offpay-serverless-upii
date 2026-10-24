"""Quick self-test: simulates two phones and checks settlement + double-spend protection."""
import base64, json, os, tempfile, uuid
os.environ["OFFPAY_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
import app as offpay

offpay.init_db()
client = offpay.app.test_client()


def new_phone(name):
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    user = client.post("/api/register", json={"name": name, "public_key": base64.b64encode(pub).decode()}).get_json()
    return user["id"], key


def sign(key, tx):
    message = json.dumps(tx)
    r, s = decode_dss_signature(key.sign(message.encode(), ec.ECDSA(hashes.SHA256())))
    return {"message": message, "signature": base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()}


alice, alice_key = new_phone("Alice")
bob, _ = new_phone("Bob")
client.post("/api/wallet/load", json={"user_id": alice, "amount": 500})

token = sign(alice_key, {"amount": 200, "from": alice, "time": 1, "to": bob, "tx_id": str(uuid.uuid4())})
print("first sync :", client.post("/api/sync", json={"tokens": [token]}).get_json()["results"][0]["status"])
print("replay     :", client.post("/api/sync", json={"tokens": [token]}).get_json()["results"][0]["status"])
fake = dict(token, message=token["message"].replace("200", "900"))
print("tampered   :", client.post("/api/sync", json={"tokens": [fake]}).get_json()["results"][0]["status"])
print("alice:", client.get(f"/api/user/{alice}").get_json())
print("bob  :", client.get(f"/api/user/{bob}").get_json())
