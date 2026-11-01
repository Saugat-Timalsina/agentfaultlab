"""Small explicit recovery registry. Recipes see task inputs and observations only."""

from dataclasses import dataclass

from agentfaultlab.schemas import ToolCall


@dataclass(frozen=True)
class Recipe:
    correction_fields: tuple[str, ...] = ()
    fallback_tool: str | None = None
    verification_tool: str | None = None
    key_field: str | None = None
    content_fields: tuple[str, ...] = ()
    independent_source: str | None = None

    def correct(self, call, bindings):
        if not self.correction_fields:
            return None
        if all(field in bindings for field in self.correction_fields):
            return {field: bindings[field] for field in self.correction_fields}
        return None

    def verification_args(self, call):
        if not isinstance(call.arguments, dict) or self.key_field not in call.arguments:
            return None
        return {self.key_field: call.arguments[self.key_field]}

    def matches(self, record, call):
        return all(
            record.get(field) == call.arguments.get(field)
            for field in (self.key_field, *self.content_fields)
        )


def recipe_registry() -> dict[str, Recipe]:
    return {
        "lookup_primary": Recipe(("key",), fallback_tool="lookup_secondary"),
        "lookup_secondary": Recipe(("key",)),
        "create_ticket": Recipe(
            ("title", "idempotency_key"),
            verification_tool="find_ticket",
            key_field="idempotency_key",
            content_fields=("title",),
        ),
        **{
            f"create_{service}_ticket": Recipe(
                ("title", "request_key"),
                verification_tool=f"find_{service}_ticket",
                key_field="request_key",
                content_fields=("title",),
            )
            for service in ("correlation", "idempotent")
        },
        "get_invoice_primary": Recipe(independent_source="get_invoice_reference"),
    }


def correction_target(call: ToolCall, registry):
    name = call.name
    if name.endswith("_typo") and name[:-5] in registry:
        name = name[:-5]
    return name
