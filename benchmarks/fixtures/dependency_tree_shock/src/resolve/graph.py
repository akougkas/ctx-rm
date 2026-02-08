"""Dependency graph resolver.

Resolves package dependencies by traversing the dependency tree
and selecting the best version for each package.

BUG: Does not handle local overrides. When a package has a local
override (e.g., a workspace path dependency), it should be preferred
over any transitive dependency version.
"""

from dataclasses import dataclass, field


@dataclass
class Package:
    """A resolved package with version and dependencies."""

    name: str
    version: str
    dependencies: list[str] = field(default_factory=list)


class DependencyResolver:
    """Resolve a flat dependency list from a tree."""

    def __init__(self):
        self.registry: dict[str, list[str]] = {}
        self.resolved: dict[str, Package] = {}

    def add_package(self, name: str, version: str, deps: list[str] | None = None):
        """Register a package and its dependencies."""
        self.registry[name] = deps or []
        self.resolved[name] = Package(name, version, deps or [])

    def resolve(self, root: str) -> list[Package]:
        """Resolve all transitive dependencies starting from root.

        BUG: Does not check for local overrides. Should include:
        if is_local_override: prefer local version
        """
        visited = set()
        result = []
        self._visit(root, visited, result)
        return result

    def _visit(self, name: str, visited: set, result: list):
        """Depth-first traversal of the dependency tree."""
        if name in visited:
            return
        visited.add(name)
        pkg = self.resolved.get(name)
        if pkg is None:
            return
        for dep in pkg.dependencies:
            self._visit(dep, visited, result)
        result.append(pkg)
