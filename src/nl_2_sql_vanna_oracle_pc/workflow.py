"""Project-owned workflow handler with Vietnamese UI messages."""

from typing import TYPE_CHECKING, Any, Dict

from vanna.components import RichTextComponent, UiComponent
from vanna.core.workflow import DefaultWorkflowHandler, WorkflowResult

if TYPE_CHECKING:
    from vanna.core.agent.agent import Agent
    from vanna.core.storage import Conversation
    from vanna.core.user.models import User

WELCOME_MESSAGE = (
    "# 👋 Chào mừng bạn đến với Vanna AI\n\n"
    "Tôi là trợ lý phân tích dữ liệu AI. Hãy hỏi tôi bất cứ điều gì về dữ liệu Oracle "
    "bằng tiếng Việt!\n\n"
    "Gõ `/help` để xem các lệnh có thể dùng."
)

SETUP_REQUIRED_MESSAGE = (
    "# ⚠️ Cần cấu hình\n\n"
    "Vanna AI cần được cấu hình trước khi có thể giúp bạn phân tích dữ liệu."
)


class AtfmWorkflowHandler(DefaultWorkflowHandler):
    """Vietnamese starter UI and command responses."""

    async def try_handle(
        self,
        agent: "Agent",
        user: "User",
        conversation: "Conversation",
        message: str,
    ) -> WorkflowResult:
        if message.strip().lower() in ["/help", "help", "/h"]:
            is_admin = "admin" in user.group_memberships

            help_content = (
                "## 🤖 Trợ lý Vanna AI\n\n"
                "Tôi là trợ lý phân tích dữ liệu! Tôi có thể giúp bạn:\n\n"
                "**💬 Truy vấn bằng ngôn ngữ tự nhiên**\n"
                '- "Cho tôi xem dữ liệu chuyến bay tháng trước"\n'
                '- "Sân bay nào có nhiều chuyến bay nhất?"\n'
                '- "Tạo biểu đồ số chuyến bay theo tháng"\n\n'
                "**🔧 Lệnh**\n"
                "- `/help` - Hiển thị thông báo trợ giúp này\n"
            )

            if is_admin:
                help_content += (
                    "\n**🔒 Lệnh quản trị**\n"
                    "- `/status` - Kiểm tra trạng thái cấu hình\n"
                    "- `/memories` - Xem và quản lý bộ nhớ gần đây\n"
                    "- `/delete [id]` - Xóa bộ nhớ theo ID\n"
                )

            help_content += (
                "\n\nHãy hỏi tôi bất cứ điều gì về dữ liệu Oracle bằng tiếng Việt!"
            )

            return WorkflowResult(
                should_skip_llm=True,
                components=[
                    UiComponent(
                        rich_component=RichTextComponent(
                            content=help_content,
                            markdown=True,
                        ),
                        simple_component=None,
                    )
                ],
            )

        return await super().try_handle(agent, user, conversation, message)

    def _generate_user_starter_card(self, analysis: Dict[str, Any]) -> UiComponent:
        content = SETUP_REQUIRED_MESSAGE if not analysis["has_sql"] else WELCOME_MESSAGE

        return UiComponent(
            rich_component=RichTextComponent(content=content, markdown=True),
            simple_component=None,
        )


def create_workflow_handler() -> AtfmWorkflowHandler:
    return AtfmWorkflowHandler()
