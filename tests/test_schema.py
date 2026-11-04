"""配置 schema 必须能被 AstrBot 的解析器吃下。

AstrBot 在加载插件时用 `_config_schema_to_default_config` 把 schema 转成默认
配置：它遍历 schema 的每一层，要求每个节点都有 `type`，且类型在它认识的
DEFAULT_VALUE_MAP 里。分组（object）还要有 `items`。

这里照抄那套逻辑跑一遍，避免再出现「装不上，报 KeyError: 'type'」。
"""

import json
from pathlib import Path

import pytest

# 与 astrbot/core/config/default.py 的 DEFAULT_VALUE_MAP 对齐（v4.29.4）
DEFAULT_VALUE_MAP = {
    "int": 0,
    "float": 0.0,
    "bool": False,
    "string": "",
    "text": "",
    "list": [],
    "file": [],
    "object": {},
    "template_list": [],
    "dict": {},
}

SCHEMA_PATHS = {
    "jev_gateway": Path("/workspace/astrbot_plugin_jev_gateway/_conf_schema.json"),
    "angel_heart": Path("/workspace/astrbot_plugin_angel_heart/_conf_schema.json"),
    "soupai": Path("/workspace/astrbot_plugin_soupai/_conf_schema.json"),
    "emoji_like": Path("/workspace/astrbot_plugin_emoji_like/_conf_schema.json"),
}


def parse_like_astrbot(schema: dict) -> dict:
    """复刻 AstrBot 的 _config_schema_to_default_config。"""
    conf: dict = {}

    def _parse_schema(node: dict, conf: dict) -> None:
        for key, value in node.items():
            assert isinstance(value, dict), f"配置项 {key} 不是对象"
            assert "type" in value, f"配置项 {key} 缺少 type"
            assert value["type"] in DEFAULT_VALUE_MAP, (
                f"配置项 {key} 的类型 {value['type']} 不受支持"
            )
            default = value.get("default", DEFAULT_VALUE_MAP[value["type"]])
            if value["type"] == "object":
                assert "items" in value, f"分组 {key} 缺少 items"
                conf[key] = {}
                _parse_schema(value["items"], conf[key])
            else:
                conf[key] = default

    _parse_schema(schema, conf)
    return conf


@pytest.mark.parametrize("name", sorted(SCHEMA_PATHS))
def test_schema_parses(name):
    path = SCHEMA_PATHS[name]
    if not path.exists():
        pytest.skip(f"{path} 不存在")
    schema = json.loads(path.read_text(encoding="utf-8"))
    conf = parse_like_astrbot(schema)
    assert conf, "解析结果为空"


def test_gateway_schema_group_has_type():
    schema = json.loads(SCHEMA_PATHS["jev_gateway"].read_text(encoding="utf-8"))
    for group, meta in schema.items():
        assert meta.get("type") == "object", f"分组 {group} 的 type 应为 object"
        assert "items" in meta, f"分组 {group} 缺少 items"


def test_gateway_schema_templates_use_name():
    """前端 TemplateListEditor 读的是 name，不是 label。"""
    schema = json.loads(SCHEMA_PATHS["jev_gateway"].read_text(encoding="utf-8"))
    templates = schema["gateway"]["items"]["api_entries"]["templates"]
    assert templates, "没有登记任何模板"
    for key, meta in templates.items():
        assert "name" in meta, f"模板 {key} 缺少 name"
        assert "items" in meta, f"模板 {key} 缺少 items"
        for field, spec in meta["items"].items():
            assert "type" in spec, f"模板 {key} 的字段 {field} 缺少 type"
            assert spec["type"] in DEFAULT_VALUE_MAP


def test_gateway_default_entry_matches_a_template():
    """默认条目必须带 __template_key，且字段与某个模板对得上。"""
    schema = json.loads(SCHEMA_PATHS["jev_gateway"].read_text(encoding="utf-8"))
    api_entries = schema["gateway"]["items"]["api_entries"]
    templates = api_entries["templates"]
    for entry in api_entries.get("default", []):
        key = entry.get("__template_key")
        assert key in templates, f"默认条目用了未知模板 {key}"
        for field in templates[key]["items"]:
            assert field in entry, f"默认条目缺少字段 {field}"


def test_gateway_plugin_reads_the_same_nesting(make_plugin):
    """插件读配置的路径要和框架生成的嵌套结构对得上。

    框架把分组的 items 摊平到分组键下，插件必须按这个形状读。
    """
    schema = json.loads(SCHEMA_PATHS["jev_gateway"].read_text(encoding="utf-8"))
    conf = parse_like_astrbot(schema)
    assert "gateway" in conf
    assert "api_entries" in conf["gateway"]
    assert "items" not in conf["gateway"], "框架给的是摊平结构"

    plugin = make_plugin(items={k: v for k, v in conf["gateway"].items() if k != "enabled"})
    assert plugin._items()["port"] == conf["gateway"]["port"]
    assert plugin._items()["api_entries"] == conf["gateway"]["api_entries"]
    assert plugin._build_registry()["systemone"][0].url == "https://jevmodel.org/v1/systemone"


def test_gateway_has_load_balancing_fields():
    """网关级有策略下拉，入口级有优先级与权重。"""
    schema = json.loads(SCHEMA_PATHS["jev_gateway"].read_text(encoding="utf-8"))
    gateway = schema["gateway"]["items"]

    strategy = gateway["lb_strategy"]
    assert strategy["type"] == "string"
    assert strategy["options"] == [
        "round_robin",
        "random",
        "weighted",
        "least_failure",
    ]
    assert len(strategy["labels"]) == len(strategy["options"])

    templates = gateway["api_entries"]["templates"]
    for key, meta in templates.items():
        fields = meta["items"]
        assert fields["priority"]["type"] == "int"
        assert fields["weight"]["type"] == "int"
        assert fields["priority"]["default"] == 100
        assert fields["weight"]["default"] == 1


def test_default_entry_carries_priority_and_weight():
    schema = json.loads(SCHEMA_PATHS["jev_gateway"].read_text(encoding="utf-8"))
    for entry in schema["gateway"]["items"]["api_entries"]["default"]:
        assert "priority" in entry
        assert "weight" in entry
