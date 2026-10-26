from dataclasses import dataclass, field


@dataclass(frozen=True)
class Principal:
    tenant: str
    user: str
    groups: tuple[str, ...] = ()
    admin: bool = False


@dataclass
class Document:
    external_id: str
    title: str
    pages: list[str]
    acl: list[str]  # user:alice, group:engineering, or tenant:all; empty denies all
    metadata: dict = field(default_factory=dict)
    uri: str = ""


def allowed(acl: list[str], principal: Principal) -> bool:
    identities = {"tenant:all", f"user:{principal.user}"}
    identities.update(f"group:{g}" for g in principal.groups)
    return bool(identities.intersection(acl))
