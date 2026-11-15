"""Reset a password from the host: python -m pricewatch.reset_password <username>"""

import getpass
import sys

from sqlalchemy import select

from .db import session_scope
from .models import User
from .services.users import hash_password


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m pricewatch.reset_password <username>")
    db = session_scope()
    try:
        user = db.scalar(select(User).where(User.username == sys.argv[1].lower()))
        if user is None:
            sys.exit(f"No user named {sys.argv[1]}")
        pw = getpass.getpass("New password (8+ characters): ")
        if len(pw) < 8 or pw != getpass.getpass("Again: "):
            sys.exit("Passwords must match and be at least 8 characters")
        user.password_hash = hash_password(pw)
        user.active = True
        db.commit()
        print(f"Password reset for {user.username}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
