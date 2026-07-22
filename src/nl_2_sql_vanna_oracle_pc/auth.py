from vanna.core.user import RequestContext, User, UserResolver

from .admin_auth import AdminAuth


class SimpleUserResolver(UserResolver):
    def __init__(self, admin_auth: AdminAuth):
        self.admin_auth = admin_auth

    async def resolve_user(self, request_context: RequestContext) -> User:
        admin_session = self.admin_auth.verify_token(
            request_context.get_cookie(self.admin_auth.cookie_name)
        )
        if admin_session is not None:
            return User(
                id=admin_session.username,
                username=admin_session.username,
                group_memberships=["admin"],
            )

        user_email = request_context.get_cookie("vanna_email") or "guest@example.com"

        return User(
            id=user_email,
            email=user_email,
            group_memberships=["user"],
        )


def create_user_resolver(admin_auth: AdminAuth) -> SimpleUserResolver:
    return SimpleUserResolver(admin_auth)

