"""
scripts/create_user.py — create or reset a Arogo account from the CLI.

A dev/admin utility for local testing. Passwords are hashed with the
same PBKDF2 the app uses, and the account is created already-verified so
it skips the email step. If the email already exists, its password is
reset (and all its old sessions revoked) rather than duplicated.

Usage:
    python scripts/create_user.py EMAIL [PASSWORD] [--name NAME]

If PASSWORD is omitted, a strong random one is generated and printed.

SECURITY: this deliberately takes an explicit email + password every
run. Never wire it to seed a fixed default admin — a known-password
account baked into a deploy is a backdoor.
"""
import argparse
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from auth import hash_password, validate_password_strength           # noqa: E402
from db.core import init_db, execute, new_id, now_iso                 # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Create or reset a Arogo account.")
    ap.add_argument("email")
    ap.add_argument("password", nargs="?", help="omit to auto-generate")
    ap.add_argument("--name", default="")
    args = ap.parse_args()

    email = args.email.strip().lower()
    password = args.password or secrets.token_urlsafe(12)
    err = validate_password_strength(password)
    if err:
        print("Password rejected:", err)
        sys.exit(1)

    init_db()
    pw_hash = hash_password(password)
    name = args.name or email.split("@")[0]
    existing = execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True)

    if existing:
        uid = existing["id"]
        execute("""UPDATE users SET password_hash=?, verified=1,
                     token_version=COALESCE(token_version,0)+1
                   WHERE id=?""", (pw_hash, uid), commit=True)
        action = "password reset"
    else:
        uid = new_id()
        execute("""INSERT INTO users (id,email,name,password_hash,verified,verify_token,created_at)
                   VALUES (?,?,?,?,1,NULL,?)""",
                (uid, email, name, pw_hash, now_iso()), commit=True)
        execute("""INSERT INTO user_profile (id,name,weight_kg,height_cm,age,gender,
                     activity_level,goal,updated_at,user_id)
                   VALUES (?, '', NULL,NULL,NULL,NULL,NULL,NULL,?,?)""",
                (new_id(), now_iso(), uid), commit=True)
        action = "created"

    print(f"\n  Account {action}:")
    print(f"    email:    {email}")
    print(f"    password: {password}")
    print(f"    user id:  {uid}")
    print("\n  Log in at http://localhost:5000  (login is by email).")
    print("  This is a normal account — Arogo has no elevated admin role.\n")


if __name__ == "__main__":
    main()
