"""Planning: turn one user request into a validated, typed plan.

The planner is the only component that talks to the model. It sends bounded,
clearly fenced text, accepts exactly one JSON object back, and then:

    parse -> type -> validate graph -> validate against the tool catalog

A plan is data. Passing this stage means the plan is *expressible*; it is not
permission, and nothing here bypasses the policy checkpoint that every step must
still cross on its own.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, StrictBool

from .catalog import ToolCatalog
from .config import AgentConfig
from .context import ContextAssembler, ContextBundle
from .errors import BudgetExceeded, ModelOutputInvalid, ModelUnavailable
from .model import MAX_PROMPT_CHARS, ModelRequest, ModelRole
from .models import AgentPlan, AgentRequest, AgentStep, Schema
from .plan_validation import ValidatedPlan, validate_plan
from .planner_schema import PLAN_SCHEMA_HINT, parse_plan_text

MAX_PROMPT_MARGIN = 256


class PlanningResult(Schema):
    plan: ValidatedPlan
    provider: str = Field(default="", max_length=64)
    model_name: str = Field(default="", max_length=128)
    tokens: int = Field(default=0, strict=True, ge=0)
    duration_ms: float = Field(default=0, ge=0)
    memory_available: StrictBool = False
    context_characters: int = Field(default=0, strict=True, ge=0)


class Planner:
    """Model-backed planner with strict structured-output handling."""

    def __init__(self, config: AgentConfig, router: Any, catalog: ToolCatalog,
                 assembler: ContextAssembler) -> None:
        self._config = config
        self._router = router
        self._catalog = catalog
        self._assembler = assembler

    def plan(self, request: AgentRequest, budget: Any, cancel: Any = None, *,
             observations: tuple[dict[str, Any], ...] = (),
             previous: ValidatedPlan | None = None,
             failure_code: str = "") -> PlanningResult:
        return self._run(request, budget, cancel, observations=observations,
                         previous=previous, failure_code=failure_code)

    def _run(self, request: AgentRequest, budget: Any, cancel: Any, *,
             observations: tuple[dict[str, Any], ...], previous: ValidatedPlan | None,
             failure_code: str) -> PlanningResult:
        budget.check_deadline()
        version = (previous.version + 1) if previous is not None else 1
        if version > 4:
            raise ModelUnavailable("plan version limit reached")
        state = "recovering" if previous is not None else "planning"
        summary = previous.objective_view() if previous is not None else None
        if failure_code and summary is not None:
            summary["failure_code"] = failure_code[:64]
        bundle = self._assembler.assemble(request, state=state, plan_summary=summary,
                                          observations=observations, budget=budget)
        prompt = self._prompt(bundle)
        model_request = ModelRequest(
            prompt=prompt,
            max_output_tokens=self._config.max_model_output_tokens,
            timeout=self._config.model_timeout_seconds,
            role=ModelRole.PLANNING,
        )
        response = self._router.generate(model_request, cancel)
        if not response.ok:
            raise ModelUnavailable(response.state.value)
        budget.add_model_tokens(response.tokens)
        output = parse_plan_text(response.text, max_bytes=self._config.max_model_output_bytes,
                                 max_steps=self._config.max_plan_steps)
        plan = self._to_plan(output, request.request_id, version)
        validated = validate_plan(plan, self._catalog, self._config)
        return PlanningResult(plan=validated, provider=response.provider,
                              model_name=response.model_name, tokens=response.tokens,
                              duration_ms=response.duration_ms,
                              memory_available=bundle.memory_available,
                              context_characters=bundle.characters)

    def preview_plan(self, request: AgentRequest, budget: Any, cancel: Any = None) -> ValidatedPlan:
        """Build and validate a plan without executing any step."""
        return self.plan(request, budget, cancel).plan

    def _prompt(self, bundle: ContextBundle) -> str:
        tools = json.dumps(self._catalog.describe(), ensure_ascii=True, separators=(",", ":"))
        sections = (
            bundle.instructions,
            f"TOOLS:\n{tools}",
            f"RESPONSE JSON SHAPE:\n{PLAN_SCHEMA_HINT}",
            f"USER REQUEST:\n{bundle.request_text}",
            f"DATA:\n{bundle.data_json}",
        )
        prompt = "\n\n".join(sections)
        if len(prompt) > MAX_PROMPT_CHARS - MAX_PROMPT_MARGIN:
            raise BudgetExceeded("planning prompt exceeds the context budget")
        return prompt

    @staticmethod
    def _to_plan(output: Any, request_id: str, version: int) -> AgentPlan:
        steps = tuple(
            AgentStep(
                step_id=item.step_id,
                tool_id=item.tool_id,
                operation=item.operation,
                arguments=item.arguments,
                dependencies=item.dependencies,
                timeout=item.timeout,
                retry_policy=item.retry_policy(),
                expected_observation=item.expected_observation,
                verification_rule=item.verification.to_rule(),
            )
            for item in output.steps
        )
        try:
            return AgentPlan(request_id=request_id, version=version, objective=output.objective,
                             steps=steps)
        except Exception:
            raise ModelOutputInvalid("model plan is not a valid dependency graph") from None
