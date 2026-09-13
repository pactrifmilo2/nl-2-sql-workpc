"""Deterministic guards for common ATFM question ambiguities."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from vanna.core.llm import LlmMessage


FLIGHT_NUMBER_PATTERN = re.compile(r"\b[A-Z]{2,3}\d{2,4}\b")
AIRPORT_CODE_PATTERN = re.compile(r"\b[A-Z]{3,4}\b")
EXPLICIT_PERIOD_PATTERN = re.compile(
    r"(\b\d+\s*(ngay|tuan|thang|nam)\b|"
    r"\b(hom nay|hom qua|ngay mai|tuan nay|thang nay|nam nay)\b|"
    r"\bngay\s+\d{1,2}\b|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b|"
    r"\b\d{4}-\d{2}-\d{2}\b)",
)


@dataclass(frozen=True)
class ClarificationChoice:
    label: str
    message: str


@dataclass(frozen=True)
class ClarificationRequirement:
    kind: str
    question: str
    options: tuple[ClarificationChoice, ...] = field(default_factory=tuple)

    def to_tool_arguments(self) -> dict[str, object]:
        return {
            "question": self.question,
            "options": [
                {"label": option.label, "message": option.message}
                for option in self.options
            ],
        }


def find_required_clarification(
    messages: list[LlmMessage],
    *,
    background_enabled: bool = False,
) -> ClarificationRequirement | None:
    """Return a clarification that must happen before any SQL tool call."""

    if not messages or messages[-1].role != "user":
        return None

    original = messages[-1].content.strip()
    normalized = _normalize_vietnamese(original)

    requirement = _unresolved_flight_reference(messages, normalized)
    if requirement:
        return requirement

    if _has_unbounded_flight_listing(normalized):
        scope_options = [
            ClarificationChoice("Hôm nay", f"{original} trong hôm nay"),
            ClarificationChoice(
                "7 ngày gần nhất",
                f"{original} trong 7 ngày gần nhất",
            ),
        ]
        if background_enabled:
            scope_options.append(
                ClarificationChoice(
                    "Chạy nền",
                    f"Chạy nền và thông báo khi hoàn thành: {original}",
                )
            )
        else:
            scope_options.append(
                ClarificationChoice(
                    "30 ngày gần nhất",
                    f"{original} trong 30 ngày gần nhất",
                )
            )
        return ClarificationRequirement(
            kind="query_scope",
            question="Bạn muốn xem danh sách chuyến bay trong khoảng thời gian nào?",
            options=tuple(scope_options),
        )

    if _has_vague_period(normalized):
        return ClarificationRequirement(
            kind="date_range",
            question="Bạn muốn xem dữ liệu trong khoảng thời gian nào?",
            options=(
                ClarificationChoice("Hôm nay", f"{original} trong hôm nay"),
                ClarificationChoice(
                    "7 ngày gần nhất",
                    f"{original} trong 7 ngày gần nhất",
                ),
                ClarificationChoice(
                    "30 ngày gần nhất",
                    f"{original} trong 30 ngày gần nhất",
                ),
            ),
        )

    if _asks_for_nearest_flight(normalized):
        return ClarificationRequirement(
            kind="flight_status",
            question="Bạn muốn tìm chuyến bay sắp tới hay chuyến bay đã hoàn thành gần nhất?",
            options=(
                ClarificationChoice(
                    "Chuyến bay sắp tới",
                    f"{original} — hiểu là chuyến bay sắp tới",
                ),
                ClarificationChoice(
                    "Đã hoàn thành gần nhất",
                    f"{original} — hiểu là chuyến bay đã hoàn thành gần nhất",
                ),
            ),
        )

    if _compares_unnamed_airports(original, normalized):
        return ClarificationRequirement(
            kind="airport",
            question="Bạn muốn so sánh hai sân bay nào? Vui lòng nhập hai mã sân bay.",
        )

    if _has_unspecified_delay_type(normalized):
        return ClarificationRequirement(
            kind="delay_metric",
            question="Bạn muốn xác định chuyến bay trễ theo giờ cất cánh hay giờ hạ cánh?",
            options=(
                ClarificationChoice(
                    "Trễ cất cánh",
                    f"{original} — so sánh giờ cất cánh thực tế với dự kiến",
                ),
                ClarificationChoice(
                    "Trễ hạ cánh",
                    f"{original} — so sánh giờ hạ cánh thực tế với dự kiến",
                ),
            ),
        )

    if _groups_by_unspecified_airport(normalized):
        return ClarificationRequirement(
            kind="airport_role",
            question="Bạn muốn thống kê theo sân bay đi hay sân bay đến?",
            options=(
                ClarificationChoice(
                    "Sân bay đi",
                    f"{original} — nhóm theo sân bay đi",
                ),
                ClarificationChoice(
                    "Sân bay đến",
                    f"{original} — nhóm theo sân bay đến",
                ),
            ),
        )

    if _chart_has_no_dimension(original, normalized):
        return ClarificationRequirement(
            kind="grouping",
            question="Bạn muốn biểu đồ nhóm số chuyến bay theo tiêu chí nào?",
            options=(
                ClarificationChoice(
                    "Theo ngày",
                    f"{original} — nhóm theo ngày",
                ),
                ClarificationChoice(
                    "Theo sân bay đi",
                    f"{original} — nhóm theo sân bay đi",
                ),
                ClarificationChoice(
                    "Theo sân bay đến",
                    f"{original} — nhóm theo sân bay đến",
                ),
            ),
        )

    return None


def _normalize_vietnamese(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return without_marks.replace("đ", "d")


def _unresolved_flight_reference(
    messages: list[LlmMessage],
    normalized: str,
) -> ClarificationRequirement | None:
    if not re.search(r"\b(chuyen bay|flight)\s+(do|nay|kia)\b", normalized):
        return None

    flight_numbers = _flight_numbers_in_previous_turn(messages)
    if len(flight_numbers) == 1:
        return None

    options = tuple(
        ClarificationChoice(
            flight_number,
            f"Cho tôi xem chuyến bay {flight_number}",
        )
        for flight_number in flight_numbers[:3]
    )
    return ClarificationRequirement(
        kind="flight_reference",
        question="Bạn đang muốn xem chuyến bay nào? Vui lòng cho biết số hiệu chuyến bay.",
        options=options,
    )


def _flight_numbers_in_previous_turn(messages: list[LlmMessage]) -> list[str]:
    previous_messages = messages[:-1]
    previous_user_index = next(
        (
            index
            for index in range(len(previous_messages) - 1, -1, -1)
            if previous_messages[index].role == "user"
        ),
        None,
    )
    if previous_user_index is None:
        return []

    previous_turn = previous_messages[previous_user_index:]
    found: list[str] = []
    for message in previous_turn:
        for flight_number in FLIGHT_NUMBER_PATTERN.findall(message.content.upper()):
            if flight_number not in found:
                found.append(flight_number)
    return found


def _has_vague_period(normalized: str) -> bool:
    has_vague_phrase = bool(
        re.search(r"\b(gan day|dao gan day|thoi gian qua)\b", normalized)
    )
    return has_vague_phrase and not EXPLICIT_PERIOD_PATTERN.search(normalized)


def _has_unbounded_flight_listing(normalized: str) -> bool:
    asks_for_all_flights = bool(
        re.search(r"\b(tat ca|toan bo)\b.*\b(chuyen bay|flights?)\b", normalized)
    )
    asks_for_aggregate = bool(
        re.search(
            r"\b(bao nhieu|dem|tong so|so luong|thong ke)\b",
            normalized,
        )
    )
    return (
        asks_for_all_flights
        and not asks_for_aggregate
        and not re.search(r"\b(chay nen|background)\b", normalized)
        and not EXPLICIT_PERIOD_PATTERN.search(normalized)
    )


def _asks_for_nearest_flight(normalized: str) -> bool:
    return bool(re.search(r"\bchuyen bay\b.*\bgan nhat\b", normalized))


def _compares_unnamed_airports(original: str, normalized: str) -> bool:
    asks_to_compare = bool(
        re.search(r"\bso sanh\b.*\b(hai|2)\s+san bay\b", normalized)
    )
    airport_codes = AIRPORT_CODE_PATTERN.findall(original)
    return asks_to_compare and len(set(airport_codes)) < 2


def _has_unspecified_delay_type(normalized: str) -> bool:
    if not re.search(r"\b(tre|cham)\b", normalized):
        return False
    return not re.search(
        r"\b(cat canh|khoi hanh|ha canh|den)\b",
        normalized,
    )


def _groups_by_unspecified_airport(normalized: str) -> bool:
    return bool(
        re.search(r"\btheo\s+san bay\b", normalized)
        and not re.search(r"\btheo\s+san bay\s+(di|den)\b", normalized)
    )


def _chart_has_no_dimension(original: str, normalized: str) -> bool:
    asks_for_chart = bool(
        re.search(r"\b(bieu do|do thi|chart|graph|plot)\b", normalized)
        or re.search(r"\bvẽ\b", original.casefold())
    )
    has_dimension = bool(re.search(r"\b(theo|moi|tung)\b", normalized))
    return asks_for_chart and not has_dimension
