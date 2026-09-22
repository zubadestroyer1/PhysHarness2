"""Trusted process-local effect bindings, checked in each database transaction."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .domain import Principal
from .errors import HarnessError


@dataclass(frozen=True)
class WorkerEffects:
    actor: Principal
    task_id: str
    holder: str
    fence: int
    require_active: bool = True


current_worker_effects: ContextVar[WorkerEffects | None] = ContextVar(
    "physharness_worker_effects", default=None
)


@contextmanager
def worker_effects(actor, task_id, holder, fence, *, require_active=True):
    """Bind controller-issued task authority; never populate from model tool arguments.

    Operators may retain final uncertain checkpoint evidence after cancellation. That exception
    still requires the current lease and does not permit an agent tool to mutate inactive work.
    """
    if (
        actor.role not in {"operator", "agent"}
        or not task_id
        or not holder
        or type(fence) is not int
        or fence < 1
        or type(require_active) is not bool
        or (not require_active and actor.role != "operator")
    ):
        raise HarnessError("WORKER_EFFECT_SCOPE", "Invalid controller-issued effect binding.")
    binding = WorkerEffects(actor, task_id, holder, fence, require_active)
    existing = current_worker_effects.get()
    if existing is not None and existing != binding:
        raise HarnessError("WORKER_EFFECT_SCOPE", "Cannot replace a bound worker's authority.")
    token = current_worker_effects.set(binding)
    try:
        yield
    finally:
        current_worker_effects.reset(token)
