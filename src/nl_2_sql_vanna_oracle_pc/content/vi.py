"""Vietnamese user-facing copy for the web page and chat workflow."""

# Page shell (ui/templates/index.html, rendered by server.py)
PAGE_TITLE = "NL to SQL Assistant"
PAGE_HEADING = "NL to SQL Assistant"
PAGE_SUBTITLE = "Giao tiếp với Oracle database bằng ngôn ngữ tự nhiên."
CHAT_TITLE = "Oracle Data Assistant"

# Chat starter UI (workflow.py)
WELCOME_MESSAGE = (
    "# Chào mừng bạn đến với Oracle AI\n\n"
    "Tôi là trợ lý phân tích dữ liệu AI. Hãy hỏi tôi bất cứ điều gì về dữ liệu Oracle "
    "bằng tiếng Việt!\n\n"
    "Gõ `/help` để xem các lệnh có thể dùng."
)

SETUP_REQUIRED_MESSAGE = (
    "# Cần cấu hình\n\n"
    "Oracle AI cần được cấu hình trước khi có thể giúp bạn phân tích dữ liệu."
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
    )

    if is_admin:
        help_content += (
            "\n**Lệnh quản trị**\n"
            "- `/status` - Kiểm tra trạng thái cấu hình\n"
            "- `/memories` - Xem và quản lý bộ nhớ gần đây\n"
            "- `/delete [id]` - Xóa bộ nhớ theo ID\n"
        )

    help_content += (
        "\n\nHãy hỏi tôi bất cứ điều gì về dữ liệu Oracle bằng tiếng Việt!"
    )
    return help_content
