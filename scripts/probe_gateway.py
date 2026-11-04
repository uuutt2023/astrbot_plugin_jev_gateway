"""网关探针：检查网关是否在跑、入口是否通、上游是否回正常答案。

用法：
    python scripts/probe_gateway.py --gateway http://127.0.0.1:8770
    python scripts/probe_gateway.py --gateway http://127.0.0.1:8770 --protocol systemone

退出码：0＝全通，1＝有问题。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import aiohttp  # noqa: E402


async def probe(gateway: str, protocol: str, token: str) -> int:
    base = gateway.rstrip("/")
    headers = {"X-Jev-Gateway-Token": token} if token else {}
    problems = 0

    print("=" * 74)
    print(f"网关探针 · {base}")
    print("=" * 74)

    # 1) 存活
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/health", headers=headers) as resp:
                data = await resp.json(content_type=None)
                print(f"[1/3] 健康检查 HTTP {resp.status} · {data.get('status')}")
                if resp.status != 200:
                    problems += 1
    except Exception as exc:
        print(f"[1/3] 健康检查失败：{exc}")
        print("\n结论：网关没在跑。先确认插件已启用、端口没被占用。❌")
        return 1

    # 2) 已登记的入口
    entries = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/jev", headers=headers) as resp:
                data = await resp.json(content_type=None)
                entries = data.get("entries") or []
        print(f"[2/3] 已登记 {len(entries)} 个入口：")
        for item in entries:
            mark = "主" if item.get("primary") else "备"
            print(f"      [{mark}] {item.get('protocol'):<14} {item.get('url')}  Key {item.get('key') or '（未填）'}")
        if not entries:
            print("      （空）")
            problems += 1
    except Exception as exc:
        print(f"[2/3] 读取入口失败：{exc}")
        problems += 1

    # 3) 发一次真实请求
    print(f"[3/3] 通过协议 {protocol!r} 发一次请求：")
    body = {
        "state": "网关探针：这是一次连通性测试。",
        "questions": {
            "probe": {"type": "noul", "instructions": "Is this connectivity probe reachable?"}
        },
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/jev/{protocol}",
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={**headers, "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                raw = await resp.read()
                status = resp.status
    except Exception as exc:
        print(f"      ✗ 请求失败：{exc}")
        problems += 1
        raw = b""
        status = 0

    if status == 200:
        try:
            data = json.loads(raw.decode("utf-8"))
            answers = data.get("answers") or {}
            print(f"      ✓ HTTP 200 · 答案 {json.dumps(answers, ensure_ascii=False)[:120]}")
        except (UnicodeDecodeError, ValueError):
            print(f"      ✓ HTTP 200 · 响应不是 JSON：{raw[:120]!r}")
    elif status == 404:
        print("      ✗ HTTP 404 · 这个协议没在网关里登记")
        problems += 1
    elif status in (401, 403):
        print("      ✗ 鉴权失败：令牌不对，或账户没激活")
        problems += 1
    elif status == 402:
        print("      ✗ 余额不足")
        problems += 1
    elif status == 429:
        print("      ✗ 被限流了，稍后再试")
        problems += 1
    elif status:
        print(f"      ✗ HTTP {status} · {raw[:200]!r}")
        problems += 1

    print("=" * 74)
    if problems:
        print(f"结论：有 {problems} 项不对，按上面的提示排查 ❌")
        return 1
    print("结论：网关与上游都通 ✅")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Jev 决策网关探针")
    parser.add_argument("--gateway", default="http://127.0.0.1:8770", help="网关地址")
    parser.add_argument("--protocol", default="systemone", help="要测的协议名")
    parser.add_argument("--token", default="", help="访问令牌（非本机访问时需要）")
    args = parser.parse_args()
    return asyncio.run(probe(args.gateway, args.protocol, args.token))


if __name__ == "__main__":
    sys.exit(main())
