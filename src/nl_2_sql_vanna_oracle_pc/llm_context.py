from vanna.core.enhancer import LlmContextEnhancer
from vanna.core.llm import LlmMessage
from vanna.core.user import User


class TableScopeEnhancer(LlmContextEnhancer):
    def __init__(self, allowed_tables: set[str], allowed_columns: set[str]):
        self.allowed_tables = sorted({table.upper() for table in allowed_tables})
        self.allowed_columns = sorted({column.upper() for column in allowed_columns})

    async def enhance_system_prompt(
        self,
        system_prompt: str,
        user_message: str,
        user: User,
    ) -> str:
        if not self.allowed_tables and not self.allowed_columns:
            return system_prompt

        table_list = ", ".join(self.allowed_tables) if self.allowed_tables else "(none configured)"
        column_list = ", ".join(self.allowed_columns) if self.allowed_columns else "(none configured)"
        constraints = f"""

## Database Schema Scope

You may only query these tables:
{table_list}

You may only use these columns in SELECT, WHERE, GROUP BY, and ORDER BY:
{column_list}

Rules:
- Users ask in Vietnamese; reply in Vietnamese. SQL identifiers and airport codes stay exactly as stored in the database.
- Map Vietnamese terms to columns: số hiệu chuyến bay=FLIGHTNBR, sân bay đi/điểm đi=FROM_AIRP, sân bay đến/điểm đến=TO_AIRP, giờ cất cánh dự kiến=ETD, giờ hạ cánh dự kiến=ETA, điểm qua cảnh/bay qua=VIA, giờ cất cánh thực tế=ATD, giờ hạ cánh thực tế=ATA.
- Map Vietnamese table intent: chuyến bay trong ngày/hôm nay=ATFM.T_DAY_FLIGHTS; chuyến bay đã hoàn thành=ATFM.T_FINISHED_FLIGHTS.
- Treat the table and column lists above as the complete schema. Do not infer, mention, join, or query anything outside them.
- Never ask the user if they want to run the query; you MUST call the run_sql tool to execute the query.
- Always use schema-qualified table names (ATFM.T_DAY_FLIGHTS or ATFM.T_FINISHED_FLIGHTS).
- SELECT only the columns needed from the allowed column list; never use SELECT * and never reference other columns.
- ATD and ATA apply to completed flights (ATFM.T_FINISHED_FLIGHTS). For same-day scheduled flights use ATFM.T_DAY_FLIGHTS with ETD and ETA.
- Generate Oracle SQL only.
- Parse Vietnamese dates (e.g. 1/1/2026, hôm nay, ngày 15 tháng 3 năm 2026) to DATE 'YYYY-MM-DD' or TO_DATE in filters on ETD, ETA, ATD, or ATA.
- Do not use T-SQL, MySQL, or PostgreSQL syntax such as TOP, LIMIT, GETDATE(), or DATE_TRUNC().
- Use FETCH FIRST n ROWS ONLY after ORDER BY when restricting row count (Oracle 12c+).
- For a specific calendar day on a datetime column, prefer: column >= DATE 'YYYY-MM-DD' AND column < DATE 'YYYY-MM-DD' + 1, or TRUNC(column) = DATE 'YYYY-MM-DD'.
- Prefer explicit column lists; include every non-aggregated SELECT column in GROUP BY.
- Do not end SQL statements with a semicolon.


"""
        return system_prompt + constraints

    async def enhance_user_messages(
        self,
        messages: list[LlmMessage],
        user: User,
    ) -> list[LlmMessage]:
        return messages


class CombinedEnhancer(LlmContextEnhancer):
    def __init__(self, enhancers: list[LlmContextEnhancer]):
        self.enhancers = enhancers

    async def enhance_system_prompt(
        self,
        system_prompt: str,
        user_message: str,
        user: User,
    ) -> str:
        enhanced = system_prompt

        for enhancer in self.enhancers:
            enhanced = await enhancer.enhance_system_prompt(
                enhanced,
                user_message,
                user,
            )

        return enhanced

    async def enhance_user_messages(
        self,
        messages: list[LlmMessage],
        user: User,
    ) -> list[LlmMessage]:
        enhanced = messages

        for enhancer in self.enhancers:
            enhanced = await enhancer.enhance_user_messages(enhanced, user)

        return enhanced
