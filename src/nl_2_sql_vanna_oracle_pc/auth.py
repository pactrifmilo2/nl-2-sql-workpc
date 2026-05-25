from vanna.core.user import RequestContext, User, UserResolver


class SimpleUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        user_email = request_context.get_cookie("vanna_email") or "guest@example.com"
        group = "admin" if user_email == "admin@example.com" else "user"

        return User(
            id=user_email,
            email=user_email,
            group_memberships=[group],
        )


def create_user_resolver() -> SimpleUserResolver:
    return SimpleUserResolver()

