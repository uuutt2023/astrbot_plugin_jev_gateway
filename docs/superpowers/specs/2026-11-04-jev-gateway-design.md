# Jev 决策网关 —— 设计文档

日期：2026-11-04

## 背景

三个插件（angel_heart、soupai、emoji_like）各自带了一套 Jev 传输层，各自的
配置页里都有 `api_key` / `base_url` / `接口协议` / `端点路径`。换网关或换 Key
要挨个改，漏改一个就出故障。

用户提出的方案：把 Jev 部分独立成一个插件，插件里登记多个 API 入口并注册
代理端口；其他插件只配一条代理地址，再指定请求协议，由网关按协议中转。

## 决策

### 1. 网关是独立插件，不是配置项

Jev 的连接信息收进 `astrbot_plugin_jev_gateway`。它起一个本地 HTTP 端口，
其他插件照常发请求，只是目标地址换成网关。

参考 `astrbot_plugin_vision_text_bridge` 的做法：独立 server、只绑回环、
用框架公开 API 而非改框架内部状态。

### 2. 路由键是「协议名」，不是端点路径

一个入口 = {协议名, 类型, 地址, Key, 模型, 端点路径, 超时}。客户端请求
`POST /jev/<协议名>`，网关按名字找到入口转发。

同一个协议名可以登记多条：第一条是主入口，上游 5xx 时自动切下一条。

### 3. 透明中转，不做协议翻译

网关把请求体原样转给上游，响应也原样带回（状态码、错误体、余额字段都不改）。

理由：协议翻译的逻辑已经在各插件的传输层里（`build_payload` /
`to_systemone_response`），网关再做一份就是重复实现，且两边规则会漂移。
客户端的 `接口协议` 配置决定它自己发什么格式，网关入口的协议类型要与之一致。

代价：客户端的 `接口协议` 和网关入口的协议类型需要对齐。已在两边文档里写明。

### 4. 客户端保留直连能力

新增两个配置项：

- `proxy_url`：网关地址，留空＝直连（老配置零影响）
- `proxy_protocol`：网关里的协议名

优先级：`proxy_url` 有值 → 走网关；否则按原逻辑直连。走网关时不再要求
插件自己填 Key，请求头里也不带 Authorization（网关会换成上游入口的 Key）。

### 5. 中间处理做成钩子

请求进网关到响应回客户端之间留两个钩子：`before_forward` / `after_response`。
内置只做「补 model」和「日志脱敏」，自定义逻辑放插件目录下的 `hooks_ext.py`，
热重载即生效。

## 组件

```
astrbot_plugin_jev_gateway/
├── main.py              插件类：读配置、起停 server、/jev网关 指令
├── core/
│   ├── entries.py       入口注册表：解析配置、协议名 → 入口列表、URL 拼接
│   ├── server.py        aiohttp server：路由、鉴权、故障转移
│   ├── relay.py         转发到上游：换鉴权、透传响应、错误映射
│   └── hooks.py         前后置钩子 + hooks_ext.py 自动加载
└── _conf_schema.json    template_list 配置多个 API 入口
```

### 配置形态

入口列表用 AstrBot 原生的 `template_list` 渲染，模板键即协议类型
（systemone / decisions / custom），每条入口带 `__template_key`。

## 路由

| 端点 | 行为 |
|---|---|
| `POST /jev/<协议名>` | 转发到该协议的入口 |
| `POST /v1/systemone`、`POST /v1/decisions` | 协议快捷入口 |
| `GET /jev` | 列出入口（Key 打码） |
| `GET /health` | 存活检查 |

## 错误映射

- 上游超时 → 504
- 上游连不上 → 502
- 上游 4xx/5xx → 原样透传（客户端能读到上游的错误体）
- 协议未登记 → 404，响应体带已登记的协议名

## 测试

- `tests/test_entries.py`：入口解析、协议名路由、URL 拼接、Key 打码
- `tests/test_relay.py`：请求体透传、鉴权替换、model 注入、超时/连接错误映射
- `tests/test_server.py`：路由、鉴权、故障转移、配置热读
- `tests/test_e2e.py`：真起 HTTP server 打一遍，验证上游收到的路径/鉴权/body

客户端侧新增 `tests/test_jev_gateway_route.py`：请求确实打到
`{网关}/jev/{协议}`、不带自己的鉴权、请求体形状不变、没 Key 也能发。

## 已知限制

- 网关是 HTTP 明文，只适合本机或可信内网；要跨机器用请自行加 TLS 反代。
- 客户端的 `接口协议` 必须与网关入口的协议类型一致，网关不做转换。
- `GET /jev` 会返回入口地址，给局域网里能访问该端口的人看；介意就别用 0.0.0.0。
