"""Eviction policies — pluggable algorithms for deciding what to remove."""

from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.policies.budget import BudgetAwarePolicy
from ctx_rm.core.policies.clock import ClockPolicy
from ctx_rm.core.policies.lru import LRUPolicy

__all__ = ["BudgetAwarePolicy", "ClockPolicy", "EvictionPolicy", "LRUPolicy"]
