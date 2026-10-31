"""Create a production FinSight user without exposing a password in shell history."""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.infrastructure.auth.password import hash_password
from app.infrastructure.db.models.user import User
from app.infrastructure.db.session import SessionLocal


def _password_from_terminal() -> str:
    password = getpass.getpass("Senha: ")
    confirmation = getpass.getpass("Confirme a senha: ")
    if password != confirmation:
        raise ValueError("As senhas não conferem.")
    if len(password) < 12:
        raise ValueError("Use uma senha com pelo menos 12 caracteres.")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cria ou redefine um usuário FinSight."
    )
    parser.add_argument("email", help="E-mail que será usado no login")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Redefine a senha de um usuário existente",
    )
    args = parser.parse_args()
    email = args.email.strip().lower()
    if "@" not in email:
        parser.error("Informe um e-mail válido.")

    try:
        password = _password_from_terminal()
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None and not args.reset_password:
            print(
                "Erro: já existe um usuário com este e-mail. "
                "Use --reset-password para trocar a senha.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if user is None:
            user = User(
                email=email, password_hash=hash_password(password), is_active=True
            )
            db.add(user)
            message = "Usuário criado"
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
            message = "Senha redefinida"
        db.commit()
    print(f"{message}: {email}")


if __name__ == "__main__":
    main()
