"""入口注册表：把配置里的 api_entries 解析成可路由的 Entry。

同名协议可以登记多条：第一条是主入口，其余作为故障转移（failover）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

KIND_SYSTEMONE = "systemone"
KIND_DECISIONS = "decisions"
KIND_CUSTOM = "custom"

#: 各协议类型的默认端点路径
DEFAULT_ENDPOINTS = {
    KIND_SYSTEMONE: "/v1/systemone",
    KIND_DECISIONS: "/v1/decisions",
}

#: 协议名 → 类型（用于「自定义协议」入口按名字回查默认路径）
KNOWN_KINDS = (KIND_SYSTEMONE, KIND_DECISIONS, KIND_CUSTOM)


@dataclass
class Entry:
    """一个可路由的上游入口。"""

    protocol: str
    kind: str = KIND_SYSTEMONE
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    endpoint_path: str = ""
    timeout: float = 10.0
    headers: dict[str, str] = field(default_factory=dict)
    balance_url: str = ""
    balance_field: str = ""
    priority: int = 100
    weight: int = 1
    index: int = 0

    @property
    def id(self) -> str:
        """入口的唯一标识。

        同一协议可以登记多个入口，协议名不再唯一，所以带上配置里的序号。
        """
        return f"{self.protocol}#{self.index}"

    @property
    def url(self) -> str:
        """上游完整地址。"""
        base = self.base_url.strip().rstrip("/")
        if not base:
            return ""
        path = self.endpoint_path.strip()
        if path and not path.startswith("/"):
            path = "/" + path
        if not path:
            path = DEFAULT_ENDPOINTS.get(self.kind, "")
        if base.endswith(path) if path else False:
            return base
        return base + path

    def masked_key(self) -> str:
        """打码后的 Key，仅用于展示。"""
        key = self.api_key or ""
        if len(key) <= 8:
            return "***" if key else ""
        return f"{key[:4]}...{key[-4:]}"

    def describe(self) -> dict:
        """对外可安全展示的信息（不含明文 Key）。"""
        return {
            "protocol": self.protocol,
            "kind": self.kind,
            "url": self.url,
            "model": self.model,
            "key": self.masked_key(),
            "balance_url": self.balance_url,
            "balance_field": self.balance_field,
            "priority": self.priority,
            "weight": self.weight,
        }


def _as_float(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _as_str(value) -> str:
    return str(value).strip() if value is not None else ""


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_entry(raw: dict) -> Entry | None:
    """把一条模板列表配置解析成 Entry；缺协议名或地址的丢弃。"""
    if not isinstance(raw, dict):
        return None
    protocol = _as_str(raw.get("protocol"))
    if not protocol:
        return None
    # 模板编辑器会带上 __template_key（systemone/decisions/custom），它就是协议类型
    kind = _as_str(raw.get("__template_key")) or _as_str(raw.get("kind")) or KIND_SYSTEMONE
    if kind not in KNOWN_KINDS:
        kind = KIND_CUSTOM
    headers = raw.get("headers")
    return Entry(
        protocol=protocol,
        kind=kind,
        base_url=_as_str(raw.get("base_url")),
        api_key=_as_str(raw.get("api_key")),
        model=_as_str(raw.get("model")),
        endpoint_path=_as_str(raw.get("endpoint_path")),
        timeout=_as_float(raw.get("timeout"), 10.0),
        headers={str(k): str(v) for k, v in headers.items()}
        if isinstance(headers, dict)
        else {},
        balance_url=_as_str(raw.get("balance_url")),
        balance_field=_as_str(raw.get("balance_field")),
        priority=_as_int(raw.get("priority"), 100),
        weight=_as_int(raw.get("weight"), 1),
    )


def build_registry(raw_entries) -> dict[str, list[Entry]]:
    """协议名 → 入口列表（按配置顺序，第一个是主入口）。"""
    registry: dict[str, list[Entry]] = {}
    if not isinstance(raw_entries, list):
        return registry
    for index, raw in enumerate(raw_entries):
        entry = parse_entry(raw)
        if entry is None:
            continue
        entry.index = index
        registry.setdefault(entry.protocol, []).append(entry)
    return registry


def resolve(registry: dict[str, list[Entry]], protocol: str) -> Entry | None:
    """取某协议的主入口。"""
    entries = registry.get(_as_str(protocol))
    return entries[0] if entries else None


def failovers(registry: dict[str, list[Entry]], protocol: str) -> list[Entry]:
    """取某协议的备用入口（不含主入口）。"""
    entries = registry.get(_as_str(protocol)) or []
    return entries[1:]
