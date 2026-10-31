"""Task/CaseSet projections in existing context, never a second asset database."""

from copy import deepcopy


class TaskContext:
    def __init__(self, conversation):
        self.conversation = conversation
        self.state = deepcopy(
            (conversation.context or {}).get("workbench_plan")
            or {
                "schema_version": 1,
                "goals": [],
                "constraints": [],
                "source_catalog": {},
                "case_set": [],
                "status": "idle",
            }
        )

    def write(self):
        self.conversation.context = {
            **(self.conversation.context or {}),
            "workbench_plan": deepcopy(self.state),
        }
        return deepcopy(self.state)

    def remember_sources(self, rows):
        catalog = self.state.setdefault("source_catalog", {})
        for row in rows:
            # Discovery is untrusted evidence, not authority. Every use re-resolves.
            catalog[row["ref"]] = {
                key: deepcopy(row[key])
                for key in ("ref", "kind", "version", "source_ref")
                if key in row
            }
        while len(catalog) > 500:
            del catalog[next(iter(catalog))]
        return self.write()

    def plan(self, goals, constraints=()):
        self.state.update(
            goals=list(goals)[:20], constraints=list(constraints)[:40], status="planning"
        )
        return self.write()

    def select(self, items):
        self.state["case_set"] = [
            {"ref": item["ref"], "version": str(item["version"])} for item in items
        ]
        return self.write()
