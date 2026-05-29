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
            SELECT FLIGHTNBR, FROM_AIRP, TO_AIRP, ETD, ETA, VIA, ATD, ATA
            FROM ATFM.T_FINISHED_FLIGHTS
            WHERE VIA = 'Q1/W2'
            """
        },
    ),
    ToolMemory(
        question="Cho tôi các chuyến bay ngày 1/1/2025",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT FLIGHTNBR, FROM_AIRP, TO_AIRP, ETD, ETA, VIA, ATD, ATA
            FROM ATFM.T_DAY_FLIGHTS
            WHERE FLIGHTDATE = '2025-01-01'
            """
        },
    ),
    ToolMemory(
    question="Các chuyến bay từ VHHH đến WMKK ngày 1/1/2025",
    tool_name="run_sql",
    args={
        "sql": """
        SELECT FLIGHTNBR, FROM_AIRP, TO_AIRP, ETD, ETA
        FROM ATFM.T_DAY_FLIGHTS
        WHERE FROM_AIRP = 'VHHH'
          AND TO_AIRP = 'WMKK'
          AND FLIGHTDATE = DATE '2025-01-01'
        """
    },
),
ToolMemory(
    question="Cho tôi các chuyến bay bị delay",
    tool_name="run_sql",
    args={
        "sql": """
        SELECT FLIGHTNBR, ETD, ATD
        FROM ATFM.T_DAY_FLIGHTS
        WHERE ATD > ETD
        """
    },
),
ToolMemory(
    question="Các chuyến bay có điểm dừng tại R468",
    tool_name="run_sql",
    args={
        "sql": """
        SELECT FLIGHTNBR, FROM_AIRP, TO_AIRP, VIA
        FROM ATFM.T_DAY_FLIGHTS
        WHERE VIA = 'R468'
        """
    },
),
ToolMemory(
    question="Chuyến bay nào đến SGN muộn hơn dự kiến",
    tool_name="run_sql",
    args={
        "sql": """
        SELECT FLIGHTNBR, ETA, ATA
        FROM ATFM.T_DAY_FLIGHTS
        WHERE ATA > ETA
          AND TO_AIRP = 'SGN'
        """
    },
),
]


BUSINESS_CONTEXT = [
    SCHEMA_CONTEXT,
]
