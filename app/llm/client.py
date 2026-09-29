from typing import List, Dict, Any, Optional
from app.llm.interpreter import OperatorNoteInterpreter
from app.llm.providers.base import BaseLLMProvider


class LLMClient:
    """
    LLM client orchestrating operator note interpretation with guardrails.
    """

    def __init__(self, provider: Optional[BaseLLMProvider] = None):
        self.interpreter = OperatorNoteInterpreter(provider=provider)

    async def interpret_operator_notes(
        self,
        notes: List[str],
        battery_info: Optional[Dict[str, Any]] = None,
    ):
        return await self.interpreter.interpret(notes, battery_info)
