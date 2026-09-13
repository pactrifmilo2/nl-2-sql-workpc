import uuid

from vanna.capabilities.agent_memory import AgentMemory
from vanna.core.enhancer import LlmContextEnhancer
from vanna.core.llm import LlmMessage
from vanna.core.tool import ToolContext
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
- Call run_sql immediately when the user's intent is sufficiently clear and interactive. If the user explicitly requests background execution and queue_background_sql is available, use that tool instead.
- If missing or ambiguous information would materially change the table, filters, grouping, or meaning, call ask_clarification before run_sql.
- Ask exactly one focused Vietnamese clarification question and offer two or three common choices when useful.
- Never ask whether the user wants to run the query, and never ask for optional filters or confirmation once the intent is clear.
- Never suggest generic rephrased/example questions or say you will help later.
- Always use schema-qualified table names (ATFM.T_DAY_FLIGHTS or ATFM.T_FINISHED_FLIGHTS).
- SELECT only the columns needed from the allowed column list; never use SELECT * and never reference other columns.
- ATD and ATA apply to completed flights (ATFM.T_FINISHED_FLIGHTS). For same-day scheduled flights use ATFM.T_DAY_FLIGHTS with ETD and ETA.
- Generate Oracle SQL only.
- Parse Vietnamese dates (e.g. 1/1/2026, hôm nay, ngày 15 tháng 3 năm 2026) to DATE 'YYYY-MM-DD' or TO_DATE in filters on ETD, ETA, ATD, or ATA.
- Do not use T-SQL, MySQL, or PostgreSQL syntax such as TOP, LIMIT, GETDATE(), or DATE_TRUNC().
- Use FETCH FIRST n ROWS ONLY after ORDER BY when restricting row count (Oracle 12c+).
- For a specific calendar day on a datetime column, prefer: column >= DATE 'YYYY-MM-DD' AND column < DATE 'YYYY-MM-DD' + 1, or TRUNC(column) = DATE 'YYYY-MM-DD'.
- Never use FLIGHTDATE = SYSDATE for "hôm nay" because SYSDATE includes a time component. Use FLIGHTDATE >= TRUNC(SYSDATE) AND FLIGHTDATE < TRUNC(SYSDATE) + 1.
- Prefer explicit column lists; include every non-aggregated SELECT column in GROUP BY.
- If the user asks for a chart/graph/biểu đồ/đồ thị, generate aggregate SQL with exactly two columns: one dimension and one numeric metric.
- For charted flight counts, prefer COUNT(*) or COUNT(DISTINCT FLIGHTNBR) with GROUP BY on the dimension column.
- For charted trends over time, use TRUNC(ETD), TRUNC(ETA), TRUNC(ATD), or TRUNC(ATA) as the grouped time bucket.
- Avoid returning raw per-flight detail rows for chart requests.
- Do not end SQL statements with a semicolon.


"""
        return system_prompt + constraints

    async def enhance_user_messages(
        self,
        messages: list[LlmMessage],
        user: User,
    ) -> list[LlmMessage]:
        return messages


class ToolMemoryContextEnhancer(LlmContextEnhancer):
    """Inject similar question→SQL examples so the model need not call search first."""

    def __init__(self, agent_memory: AgentMemory | None = None):
        self.agent_memory = agent_memory

    async def enhance_system_prompt(
        self,
        system_prompt: str,
        user_message: str,
        user: User,
    ) -> str:
        if not self.agent_memory:
            return system_prompt

        try:
            context = ToolContext(
                user=user,
                conversation_id="temp",
                request_id=str(uuid.uuid4()),
                agent_memory=self.agent_memory,
            )
            matches = await self.agent_memory.search_similar_usage(
                question=user_message,
                context=context,
                limit=3,
                similarity_threshold=0.45,
                tool_name_filter="run_sql",
            )
        except Exception:
            return system_prompt

        if not matches:
            return system_prompt

        examples_section = "\n\n## Similar Successful Queries\n\n"
        examples_section += (
            "Use these as SQL patterns after the request is clear. If essential details "
            "are materially ambiguous, call ask_clarification first; otherwise call "
            "run_sql directly.\n\n"
        )

        for result in matches:
            memory = result.memory
            sql = memory.args.get("sql", "").strip()
            examples_section += f'Question: "{memory.question}"\n'
            examples_section += f"Tool: {memory.tool_name}\n"
            examples_section += f"SQL:\n```sql\n{sql}\n```\n\n"

        return system_prompt + examples_section

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
