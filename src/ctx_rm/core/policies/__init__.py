"""Eviction policies — pluggable algorithms for deciding what to remove."""

from ctx_rm.core.policies.arc import ARCPolicy as ARCPolicy
from ctx_rm.core.policies.base import EvictionPolicy as EvictionPolicy
from ctx_rm.core.policies.budget import BudgetAwarePolicy as BudgetAwarePolicy
from ctx_rm.core.policies.clock import ClockPolicy as ClockPolicy
from ctx_rm.core.policies.innodb import InnoDBPolicy as InnoDBPolicy
from ctx_rm.core.policies.lru import LRUPolicy as LRUPolicy
