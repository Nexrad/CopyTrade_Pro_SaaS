"""
scripts/create_admin.py
--------------------------
Run once to create your first admin account:

    python scripts/create_admin.py admin@example.com SomeStrongPassword123

There's no public "become admin" endpoint on purpose - the only way
to create one is this script, run locally on the machine that holds
the database.
"""

import sys
import time
import uuid

sys.path.insert(0, __file__.rsplit("/scripts", 1)[0])

from database.db import get_conn, init_db  # noqa: E402
from security.passwords import hash_password  # noqa: E402


def main():
    if len(sys.argv) != 3:
        print("Usage: python scripts/create_admin.py <email> <password>")
        sys.exit(1)

    email, password = sys.argv[1].strip().lower(), sys.argv[2]
    if len(password) < 10:
        print("Password must be at least 10 characters.")
        sys.exit(1)

    init_db()
    conn = get_conn()
    if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        print(f"A user with email {email} already exists.")
        sys.exit(1)

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO users (id, email, password_hash, role, is_active, created_at) VALUES (?, ?, ?, 'admin', 1, ?)",
        (uuid.uuid4().hex, email, hash_password(password), now),
    )
    conn.commit()
    print(f"Admin account created: {email}")


if __name__ == "__main__":
    main()
