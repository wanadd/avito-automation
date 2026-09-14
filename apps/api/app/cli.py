import argparse
import asyncio
import getpass

from sqlalchemy import select

import app.db.base  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.models.enums import OperatorRole
from app.models.operator import OperatorUser
from app.services.onboarding import pilot_readiness
from app.services.operator_auth import create_operator_user


async def create_operator(args) -> None:
    password = args.password or getpass.getpass("Password: ")
    if not password:
        raise SystemExit("Password is required")
    async with AsyncSessionLocal() as session:
        await create_operator_user(session, args.username, password, OperatorRole(args.role))
    print(f"Operator {args.username} created with role {args.role}")


async def list_operators(_args) -> None:
    async with AsyncSessionLocal() as session:
        users = list(await session.scalars(select(OperatorUser).order_by(OperatorUser.username)))
    for user in users:
        status = "active" if user.is_active else "disabled"
        print(f"{user.username}\t{user.role.value}\t{status}")


async def disable_operator(args) -> None:
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(OperatorUser).where(OperatorUser.username == args.username))
        if user is None:
            raise SystemExit("Operator not found")
        user.is_active = False
        await session.commit()
    print(f"Operator {args.username} disabled")


async def pilot_readiness_command(_args) -> None:
    async with AsyncSessionLocal() as session:
        report = await pilot_readiness(session)
    print(report["status"])
    for key, value in sorted(report["checks"].items()):
        print(f"{key}={value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-operator")
    create.add_argument("username")
    create.add_argument("--role", choices=[role.value for role in OperatorRole], default=OperatorRole.OPERATOR.value)
    create.add_argument("--password", help="Transient only; prefer interactive prompt or environment injection in automation.")
    create.set_defaults(func=create_operator)

    listed = subparsers.add_parser("list-operators")
    listed.set_defaults(func=list_operators)

    disable = subparsers.add_parser("disable-operator")
    disable.add_argument("username")
    disable.set_defaults(func=disable_operator)

    readiness = subparsers.add_parser("pilot-readiness")
    readiness.set_defaults(func=pilot_readiness_command)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
