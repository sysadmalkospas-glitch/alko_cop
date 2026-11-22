"""Local maintenance commands for the cabinet server."""

import argparse
import getpass
import sys
import warnings

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import hash_password, normalize_login
from .config import Settings, get_settings
from .models import CabinetUser


def create_first_admin(login: str, password: str, settings: Settings) -> bool:
    login = normalize_login(login)
    password_hash = hash_password(password)
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as db:
            if engine.dialect.name == "postgresql":
                db.execute(text("LOCK TABLE cabinet_users IN SHARE ROW EXCLUSIVE MODE"))
            elif engine.dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            if db.scalar(select(CabinetUser.id).limit(1)) is not None:
                return False
            db.add(CabinetUser(login=login, password_hash=password_hash, is_active=True, role="admin"))
            db.commit()
            return True
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Управление сервером AlkoCop")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="Создать первого администратора кабинета")
    create.add_argument("--login", help="Логин администратора (если не задан, будет запрошен)")
    args = parser.parse_args()
    try:
        login = args.login or input("Логин администратора: ")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Пароль (не менее 12 символов): ")
            confirmation = getpass.getpass("Повторите пароль: ")
        if password != confirmation:
            print("Пароли не совпадают.", file=sys.stderr)
            return 1
        if not create_first_admin(login, password, get_settings()):
            print("Пользователь кабинета уже существует.", file=sys.stderr)
            return 1
    except ValueError:
        print("Некорректный логин или длина пароля (12–1024 символа).", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Не удалось создать администратора. Проверьте БД и миграции.", file=sys.stderr)
        return 1
    except getpass.GetPassWarning:
        print("Запустите команду в интерактивном терминале.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        return 1
    print("Администратор создан.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
