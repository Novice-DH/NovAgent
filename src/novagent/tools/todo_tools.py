"""计划与任务状态的结构化输出工具（无副作用的载体）。"""

from typing import Any

from langchain_core.tools import StructuredTool


def create_todo_write_tool() -> StructuredTool:
    def todo_write(
        plan_summary: str,
        todos: list[dict[str, Any]],
        acceptance_criteria: list[str],
        verification_commands: list[str],
    ) -> str:
        """Submit the plan for the task.

        Args:
            plan_summary: One-paragraph summary of the approach.
            todos: Ordered steps, each with id, content, status and note.
            acceptance_criteria: Observable criteria that mean "done".
            verification_commands: Shell commands that verify the criteria.

        Returns:
            A confirmation string.
        """
        return f"Plan submitted: {plan_summary} ({len(todos)} todos)"

    return StructuredTool.from_function(todo_write, name="todo_write")


def create_todo_update_tool() -> StructuredTool:
    def todo_update(todo_id: str, status: str, note: str = "") -> str:
        """Update the status of one todo step.

        Args:
            todo_id: The id of the todo step to update.
            status: One of "pending", "in_progress", "completed", "blocked".
            note: Optional short progress note.

        Returns:
            A confirmation string.
        """
        return f"Todo {todo_id} updated to {status}"

    return StructuredTool.from_function(todo_update, name="todo_update")
