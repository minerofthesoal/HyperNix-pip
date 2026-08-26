"""noodle.swarm — many agents, many models, one task list.

A swarm is a roster of models and a queue of tasks. It runs them in
parallel, it does not re-route a failure to a different provider, and it
reports what each one cost.

Why no automatic failover
-------------------------
The obvious feature is "if the local model fails, try the frontier one".
It is a bad default in both directions. Silently escalating a task from
a local 7B to a paid API produces a surprising invoice; silently
demoting one produces surprising output. So a failure is a failure, and
:meth:`Swarm.run` reports it. :meth:`Swarm.retry_failed` exists and is
explicit about what it will re-run and where.

Task assignment
---------------
Round-robin over the roster by default, because it is predictable and
predictability is what makes a parallel run debuggable. A task can name
its own model, and :meth:`Swarm.submit` accepts a ``prefer`` to pin one —
"the cheap local model does the boilerplate, the expensive one does the
hard file" is a real workflow and worth being able to express.

Concurrency
-----------
A thread pool, not asyncio. Every provider client here is blocking
stdlib HTTP, the work is I/O-bound with long waits, and a thread per
in-flight request is the right shape at swarm sizes (single digits to
low tens). Rewriting the transport to be async would buy nothing at this
scale and cost the ability to call a synchronous verifier.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import Agent, AgentEvent, AgentResult, Verifier
from .providers import ModelClient, ProviderError, build_client
from .tools import ToolContext

logger = logging.getLogger(__name__)

__all__ = ["SwarmTask", "SwarmReport", "Swarm"]


@dataclass
class SwarmTask:
    """One unit of work for one agent."""

    task_id: str
    prompt: str
    prefer: str = ""                       # "provider:model" to pin
    tools: list[str] | None = None
    workspace: str = ""                    # subdirectory, relative to the swarm root
    system: str = ""
    max_turns: int = 12

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "prompt": self.prompt, "prefer": self.prefer,
            "tools": list(self.tools) if self.tools else None,
            "workspace": self.workspace, "max_turns": self.max_turns,
        }


@dataclass
class SwarmReport:
    results: list[AgentResult] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)

    @property
    def failed(self) -> list[AgentResult]:
        return [r for r in self.results if not r.ok]

    @property
    def total_tokens(self) -> tuple[int, int]:
        return (
            sum(r.input_tokens for r in self.results),
            sum(r.output_tokens for r in self.results),
        )

    def cost_summary(self) -> dict[str, dict[str, int]]:
        """Tokens per provider.

        Not currency: prices change weekly and a number that is quietly
        out of date is worse than no number. Tokens are what was actually
        consumed and can be multiplied by whatever the caller is paying.
        """
        out: dict[str, dict[str, int]] = {}
        for result in self.results:
            entry = out.setdefault(result.provider, {"input": 0, "output": 0, "tasks": 0})
            entry["input"] += result.input_tokens
            entry["output"] += result.output_tokens
            entry["tasks"] += 1
        return out

    def to_dict(self) -> dict[str, Any]:
        inp, out = self.total_tokens
        return {
            "ok": self.ok,
            "task_count": len(self.results),
            "failed_count": len(self.failed),
            "seconds": round(self.seconds, 2),
            "input_tokens": inp,
            "output_tokens": out,
            "by_provider": self.cost_summary(),
            "results": [r.to_dict() for r in self.results],
        }


class Swarm:
    """Runs tasks across a roster of models."""

    def __init__(
        self,
        roster: Sequence[str | ModelClient],
        root: str | Path,
        *,
        max_parallel: int = 4,
        allow_execute: bool = False,
        memory_enabled: bool = False,
        verifier: Verifier | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        if not roster:
            raise ValueError("A swarm needs at least one model in its roster")
        self.clients: list[ModelClient] = [
            entry if isinstance(entry, ModelClient) else build_client(entry) for entry in roster
        ]
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_parallel = max(1, int(max_parallel))
        self.allow_execute = allow_execute
        self.memory_enabled = memory_enabled
        self.verifier = verifier
        self.on_event = on_event

        self._tasks: list[SwarmTask] = []
        self._next_client = 0
        self._lock = threading.Lock()

    # -- roster -------------------------------------------------------

    def describe_roster(self) -> list[dict[str, Any]]:
        return [
            {
                "provider": c.spec.provider.value,
                "label": c.spec.label,
                "model": c.model,
                "paid": c.spec.paid,
                "base_url": c.base_url,
            }
            for c in self.clients
        ]

    def _client_for(self, task: SwarmTask) -> ModelClient:
        if task.prefer:
            provider, _, model = task.prefer.partition(":")
            for client in self.clients:
                if client.spec.provider.value == provider.strip().lower() and (
                    not model or client.model == model.strip()
                ):
                    return client
            # An unavailable pin is an error rather than a silent
            # substitution: the caller pinned it for a reason, and
            # quietly using something else defeats the point.
            raise ProviderError(
                f"Task {task.task_id} pinned {task.prefer!r}, which is not in this swarm's "
                f"roster ({', '.join(c.spec.provider.value for c in self.clients)}).",
                code="not_in_roster",
            )
        with self._lock:
            client = self.clients[self._next_client % len(self.clients)]
            self._next_client += 1
        return client

    # -- tasks --------------------------------------------------------

    def submit(
        self,
        prompt: str,
        *,
        task_id: str = "",
        prefer: str = "",
        tools: list[str] | None = None,
        workspace: str = "",
        system: str = "",
        max_turns: int = 12,
    ) -> SwarmTask:
        task = SwarmTask(
            task_id=task_id or f"task{len(self._tasks) + 1}",
            prompt=prompt, prefer=prefer, tools=tools,
            workspace=workspace, system=system, max_turns=max_turns,
        )
        self._tasks.append(task)
        return task

    def submit_all(self, prompts: Sequence[str], **kwargs: Any) -> list[SwarmTask]:
        return [self.submit(p, **kwargs) for p in prompts]

    # -- running ------------------------------------------------------

    def run(self, tasks: Sequence[SwarmTask] | None = None) -> SwarmReport:
        """Run tasks in parallel and report every outcome.

        Each task gets its own workspace subdirectory by default, so two
        agents writing ``main.py`` do not overwrite each other. Sharing
        one is possible (``workspace=""`` on both) and is the caller's
        decision to make deliberately.
        """
        queue = list(tasks if tasks is not None else self._tasks)
        if not queue:
            return SwarmReport()

        started = time.monotonic()
        report = SwarmReport()
        with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(queue))) as pool:
            futures: list[tuple[SwarmTask, Future]] = [
                (task, pool.submit(self._run_one, task)) for task in queue
            ]
            for task, future in futures:
                try:
                    report.results.append(future.result())
                except ProviderError as exc:
                    report.results.append(
                        AgentResult(
                            agent=task.task_id, ok=False, content="",
                            error=str(exc), provider=exc.provider,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - one task must not kill the swarm
                    logger.exception("noodle.swarm: task %s crashed", task.task_id)
                    report.results.append(
                        AgentResult(
                            agent=task.task_id, ok=False, content="",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
        report.seconds = time.monotonic() - started
        return report

    def _run_one(self, task: SwarmTask) -> AgentResult:
        client = self._client_for(task)
        workspace = self.root / (task.workspace or task.task_id)
        context = ToolContext(
            root=workspace,
            allow_execute=self.allow_execute,
            memory_enabled=self.memory_enabled,
        )
        agent = Agent(
            name=task.task_id,
            client=client,
            context=context,
            system=task.system,
            tools=task.tools,
            max_turns=task.max_turns,
            verifier=self.verifier,
            on_event=self.on_event,
        )
        return agent.run(task.prompt)

    def retry_failed(self, report: SwarmReport, *, prefer: str = "") -> SwarmReport:
        """Re-run the failed tasks, optionally on a different model.

        Explicit rather than automatic, and it says where it is sending
        the work. Automatic failover across providers is the feature this
        module deliberately does not have — see the module docstring.
        """
        failed_ids = {r.agent for r in report.failed}
        again = [t for t in self._tasks if t.task_id in failed_ids]
        if prefer:
            again = [
                SwarmTask(**{**t.to_dict(), "prefer": prefer, "tools": t.tools})
                for t in again
            ]
        return self.run(again)
