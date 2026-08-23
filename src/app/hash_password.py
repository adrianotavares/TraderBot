"""Generate the DASHBOARD_PASSWORD_HASH value for .env.

Usage:
    python src/app/hash_password.py
"""

import getpass
import sys

from werkzeug.security import generate_password_hash

MIN_LENGTH = 10


def main() -> int:
    password = getpass.getpass("Senha do dashboard: ")
    if len(password) < MIN_LENGTH:
        print(f"A senha deve ter ao menos {MIN_LENGTH} caracteres.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Confirme a senha: "):
        print("As senhas não coincidem.", file=sys.stderr)
        return 1

    digest = generate_password_hash(password, method="pbkdf2:sha256:600000")
    print("\nAdicione a linha abaixo ao seu .env:\n")
    print(f"DASHBOARD_PASSWORD_HASH='{digest}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
