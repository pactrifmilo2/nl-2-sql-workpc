"""Vietnamese user-facing copy for the web page and chat workflow."""

# Page shell (ui/templates/index.html, rendered by server.py)
PAGE_TITLE = "NL to SQL Assistant"
PAGE_HEADING = "NL to SQL Assistant"
PAGE_SUBTITLE = "Giao tiếp với Oracle database bằng ngôn ngữ tự nhiên."
CHAT_TITLE = "Oracle Data Assistant"

# Chat starter UI (workflow.py)
WELCOME_MESSAGE = (
    "# Chào mừng bạn đến với Vanna AI\n\n"
    "Tôi là trợ lý phân tích dữ liệu AI. Hãy hỏi tôi bất cứ điều gì về dữ liệu Oracle "
    "bằng tiếng Việt!\n\n"
    "Gõ `/help` để xem các lệnh có thể dùng."
)

SETUP_REQUIRED_MESSAGE = (
    "# Cần cấu hình\n\n"
    "Vanna AI cần được cấu hình trước khi có thể giúp bạn phân tích dữ liệu."
)

HITL_FEEDBACK_PROMPT = "Kết quả truy vấn có đúng không?"
HITL_THUMBS_UP_LABEL = "👍 Đúng"
HITL_THUMBS_DOWN_LABEL = "👎 Không đúng"

HITL_SAVE_SUCCESS_ADMIN = (
    "Đã lưu mẫu câu hỏi → SQL vào bộ nhớ. Các truy vấn tương tự sẽ dùng mẫu này."
)
HITL_SAVE_SUCCESS_USER = (
    "Cảm ơn phản hồi! Chỉ quản trị viên mới ghi vào bộ nhớ lâu dài; "
    "phản hồi của bạn đã được ghi nhận."
)
HITL_SAVE_NO_PENDING = "Không có truy vấn nào đang chờ lưu. Hãy chạy một câu hỏi dữ liệu trước."
HITL_SAVE_INVALID_SQL = (
    "SQL không được lưu: chỉ cho phép các bảng trong phạm vi cấu hình."
)
HITL_REJECT_MESSAGE = (
    "Đã ghi nhận phản hồi tiêu cực. Mẫu truy vấn này sẽ không được lưu vào bộ nhớ."
)
HITL_REJECT_ADMIN_HINT = (
    "\n\nQuản trị viên có thể gửi SQL đúng bằng lệnh:\n"
    "`/correct_sql SELECT ...`"
)
HITL_CORRECT_SUCCESS = "Đã lưu SQL đã chỉnh sửa vào bộ nhớ."
HITL_CORRECT_DENIED = "Chỉ quản trị viên mới có thể dùng `/correct_sql`."
HITL_CORRECT_USAGE = (
    "Cú pháp: `/correct_sql` theo sau là câu SQL Oracle (một dòng hoặc nhiều dòng)."
)


def build_help_message(*, is_admin: bool) -> str:
    help_content = (
        "## Trợ lý AI\n\n"
        "Tôi là trợ lý phân tích dữ liệu! Tôi có thể giúp bạn:\n\n"
        "**Truy vấn bằng ngôn ngữ tự nhiên**\n"
        '- "Cho tôi xem dữ liệu chuyến bay tháng trước"\n'
        '- "Sân bay nào có nhiều chuyến bay nhất?"\n'
        '- "Tạo biểu đồ số chuyến bay theo tháng"\n\n'
        "**Lệnh**\n"
        "- `/help` - Hiển thị thông báo trợ giúp này\n"
        "- Sau mỗi truy vấn thành công: 👍 `/save_to_memory` hoặc 👎 `/reject_memory`\n"
    )

    if is_admin:
        help_content += (
            "\n**Lệnh quản trị**\n"
            "- `/status` - Kiểm tra trạng thái cấu hình\n"
            "- `/memories` - Xem và quản lý bộ nhớ gần đây\n"
            "- `/delete [id]` - Xóa bộ nhớ theo ID\n"
            "- `/correct_sql <SQL>` - Lưu SQL đúng sau phản hồi 👎\n"
        )

    help_content += (
        "\n\nHãy hỏi tôi bất cứ điều gì về dữ liệu Oracle bằng tiếng Việt!"
    )
    return help_content
