"""Authentication endpoints and JWT-based dependency."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from pydantic import BaseModel, Field

from ..core import aws, security
from ..core.aws import users_table as default_users_table
from ..models.user import User, UserCredentials
from ..services import users as users_svc

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


def get_users_table():
    """Dependency that returns the users DynamoDB table.

    Tests override this with a moto-backed table.
    """
    return default_users_table()


class LoginRequest(BaseModel):
    """Login-specific schema: username must be non-empty, password is unconstrained.

    We intentionally do NOT enforce a minimum password length here — the
    authentication service handles all credential validation and always
    returns 401 (not 422) for wrong credentials, regardless of length.
    """

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
def login(creds: LoginRequest, table=Depends(get_users_table)) -> TokenResponse:
    user = users_svc.authenticate(table, creds.username, creds.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = security.create_access_token(subject=user.username)
    return TokenResponse(access_token=token)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    table=Depends(get_users_table),
) -> User:
    """Dependency: extracts JWT from Authorization header, returns User.

    Raises 401 on any failure (missing token, invalid signature, expired,
    unknown user).
    """
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = security.decode_access_token(creds.credentials)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token: no subject",
        )
    user = users_svc.get_by_username(table, username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found",
        )
    return user
