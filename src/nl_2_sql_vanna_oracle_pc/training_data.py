from vanna.capabilities.agent_memory import ToolMemory

from .schema_context import SCHEMA_CONTEXT


TRAINING_EXAMPLES = [
    ToolMemory(
        question="Cho tôi danh sách chuyến bay trong ngày từ VVNB đến VVTH.",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT FLIGHTNBR, FROM_AIRP, TO_AIRP, ETD, ETA, VIA FROM ATFM.T_DAY_FLIGHTS WHERE FROM_AIRP = 'VVNB' AND TO_AIRP = 'VVTH'
            """
        },
    ),
    ToolMemory(
        question="Cho tôi các chuyến bay đã hoàn thành đi qua Q1/W2",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT FLIGHTNBR, FROM_AIRP, TO_AIRP, ETD, ETA, VIA, ATD, ATA FROM ATFM.T_FINISHED_FLIGHTS WHERE VIA = 'DAD'
            """
        },
    ),
]


BUSINESS_CONTEXT = [
    SCHEMA_CONTEXT,
]
