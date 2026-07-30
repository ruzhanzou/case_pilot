import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from casepilot_api.config import get_settings
from casepilot_api.database import get_db_session, get_session_factory
from casepilot_api.models import (
    Account,
    AccountSession,
    CaseCollection,
    Space,
    SpaceMembership,
)
from casepilot_api.schemas import (
    AccountLogin,
    AccountRegistration,
    AccountView,
    SpaceView,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings = get_settings()
PASSWORD_ITERATIONS = 310_000
DEMO_EMAIL = "demo@casepilot.local"
DEMO_PASSWORD = "CasePilot123!"
DEMO_EXECUTOR_EMAIL = "executor@casepilot.local"
DEMO_EXECUTOR_PASSWORD = "CasePilot123!"
DbSession = Annotated[Session, Depends(get_db_session)]


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            bytes.fromhex(salt_hex),
            int(raw_iterations),
        )
        return secrets.compare_digest(digest.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def account_view(db: Session, account: Account) -> AccountView:
    rows = db.execute(
        select(Space, SpaceMembership.role)
        .join(SpaceMembership, SpaceMembership.space_id == Space.id)
        .where(SpaceMembership.account_id == account.id)
        .order_by(Space.created_at)
    ).all()
    return AccountView(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
        spaces=[
            SpaceView(
                id=space.id,
                name=space.name,
                description=space.description,
                role=role,
            )
            for space, role in rows
        ],
    )


def create_session(db: Session, response: Response, account: Account) -> None:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
    db.add(
        AccountSession(
            account_id=account.id,
            token_hash=session_token_hash(token),
            expires_at=expires_at,
        )
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.env == "production",
        path="/",
    )


def ensure_demo_account() -> None:
    """Create the documented owner and executor accounts for local acceptance."""
    with get_session_factory()() as db:
        account = db.scalar(select(Account).where(Account.email == DEMO_EMAIL))
        if account is None:
            account = Account(
                email=DEMO_EMAIL,
                display_name="体验用户",
                password_hash=hash_password(DEMO_PASSWORD),
            )
            space = Space(
                name="体验用户的质量空间",
                description="CasePilot 本地验收空间",
            )
            db.add_all([account, space])
            db.flush()
            db.add_all(
                [
                    SpaceMembership(
                        space_id=space.id,
                        account_id=account.id,
                        role="owner",
                    ),
                    CaseCollection(
                        space_id=space.id,
                        name="账号登录验收用例集",
                        description="用于验收用例管理、版本修订和 QA 执行状态记录",
                    ),
                ]
            )
        else:
            owner_membership = db.scalar(
                select(SpaceMembership)
                .where(
                    SpaceMembership.account_id == account.id,
                    SpaceMembership.role == "owner",
                )
                .order_by(SpaceMembership.created_at)
            )
            if owner_membership is None:
                return
            space = db.get(Space, owner_membership.space_id)
            if space is None:
                return

        executor = db.scalar(
            select(Account).where(Account.email == DEMO_EXECUTOR_EMAIL)
        )
        if executor is None:
            executor = Account(
                email=DEMO_EXECUTOR_EMAIL,
                display_name="执行成员",
                password_hash=hash_password(DEMO_EXECUTOR_PASSWORD),
            )
            db.add(executor)
            db.flush()
        membership = db.scalar(
            select(SpaceMembership).where(
                SpaceMembership.space_id == space.id,
                SpaceMembership.account_id == executor.id,
            )
        )
        if membership is None:
            db.add(
                SpaceMembership(
                    space_id=space.id,
                    account_id=executor.id,
                    role="member",
                )
            )
        db.commit()


def require_account(
    request: Request,
    db: DbSession,
) -> Account:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required")
    row = db.execute(
        select(AccountSession, Account)
        .join(Account, Account.id == AccountSession.account_id)
        .where(AccountSession.token_hash == session_token_hash(token))
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    account_session, account = row
    if account_session.expires_at <= datetime.now(UTC) or not account.is_active:
        db.delete(account_session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_expired")
    return account


@router.post("/register", response_model=AccountView, status_code=201)
def register(
    payload: AccountRegistration,
    response: Response,
    db: DbSession,
) -> AccountView:
    email = normalize_email(payload.email)
    existing = db.scalar(select(Account.id).where(Account.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="email_already_registered")

    account = Account(
        email=email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    space = Space(
        name=f"{payload.display_name.strip()}的质量空间",
        description="注册时自动创建的默认空间",
    )
    db.add_all([account, space])
    db.flush()
    db.add_all(
        [
            SpaceMembership(space_id=space.id, account_id=account.id, role="owner"),
            CaseCollection(
                space_id=space.id,
                name="账号登录验收用例集",
                description="用于验收用例管理、版本修订和 QA 执行状态记录",
            ),
        ]
    )
    create_session(db, response, account)
    db.commit()
    return account_view(db, account)


@router.post("/login", response_model=AccountView)
def login(
    payload: AccountLogin,
    response: Response,
    db: DbSession,
) -> AccountView:
    account = db.scalar(
        select(Account).where(Account.email == normalize_email(payload.email))
    )
    if account is None or not verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    create_session(db, response, account)
    db.commit()
    return account_view(db, account)


CurrentAccount = Annotated[Account, Depends(require_account)]


@router.get("/me", response_model=AccountView)
def me(
    account: CurrentAccount,
    db: DbSession,
) -> AccountView:
    return account_view(db, account)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: DbSession,
) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        stored = db.scalar(
            select(AccountSession).where(
                AccountSession.token_hash == session_token_hash(token)
            )
        )
        if stored is not None:
            db.delete(stored)
            db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")


def require_space_membership(
    db: Session,
    account_id: UUID,
    requested_space_id: UUID | None,
) -> SpaceMembership:
    query = (
        select(SpaceMembership)
        .where(SpaceMembership.account_id == account_id)
        .order_by(SpaceMembership.created_at)
    )
    if requested_space_id is not None:
        query = query.where(SpaceMembership.space_id == requested_space_id)
    membership = db.scalar(query)
    if membership is None:
        raise HTTPException(status_code=403, detail="space_access_denied")
    return membership
