from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

API_BASE = "https://data.dubhenexus.org/api"

# ── 航空关键词 ─────────────────────────────────────────
AVIATION_KEYWORDS = [
    "metar", "taf", "atis", "notam",
    "气象", "天气", "weather", "报文",
    "机场", "airport", "跑道", "runway",
    "起降", "航空", 
]

ICAO_PATTERN = re.compile(r"\b([A-Za-z]{4})\b")
ROUTABLE_ICAO_PREFIXES = frozenset("VZRPYOBG")
COMMAND_PLATFORMS = frozenset({"isfp", "skylite"})

# ── LLM 注入的知识 ──────────────────────────────────────
DUBHE_NEXUS_KNOWLEDGE = """
## 关于天枢互联 Dubhe Nexus

天枢互联创研工作室（Dubhe Nexus Innovation and Research Studio）是一支由模拟飞行爱好者、
开发者与 Minecraft 玩家组成的独立技术团队。我们保持轻量与灵活，拒绝复杂的商业架构，
致力于在模拟飞行生态、电子飞行包（EFB）工具及数据接口服务（Open API）上做出扎实的产出。
与此同时，我们也在虚拟世界另一端的「星图港」里，用方块构建对城市与天际线的想象。

作为学生出身的技术同好，我们信奉实用主义，以 AI 辅助开发——在学业之余，借助 AI 大模型提升开发效率，
将有限的精力集中在干净的代码和简洁的交互上，只为给社区在数据查询与协同效率上带来真正有用的帮助。

### Open API（data.dubhenexus.org）

机场数据接口：
- /api/airport/:icao        机场基础信息（名称、跑道、坐标、海拔等）
- /api/airport/metar/:icao  METAR 实时观测气象
- /api/airport/taf/:icao    TAF 航站预报
- /api/airport/atis/:icao   ATIS 通播（仅支持 VHHH 香港国际机场）
- /api/airport/notam/:icao  NOTAM 航行通告（仅支持 VHHH 香港国际机场）

在线航班接口：
- /api/flights/isfp         ISFP 在线机组
- /api/flights/skylite      SkyLite 在线机组
- /api/flights/vatsim       VATSIM 在线机组
- /api/flights/volanta      Volanta 在线机组
- /api/flights/apoc         APOC 在线机组
- /api/flights/planepals    PlanePals 在线机组

### Bot 内置指令

- /airport <ICAO>          查询机场资料详情
- /metar <ICAO>            查询 METAR 实时气象报文
- /taf <ICAO>              查询 TAF 航站预报
- /atis [DEP/ARR] <ICAO>   查询 ATIS 通播（仅 VHHH，可选 DEP/ARR 指定进离场）
- /notam                   查询 VHHH NOTAM 航行通告
- /weather <ICAO>          综合气象查询（含 METAR + TAF 解读）
- /flight <ISFP/SkyLite>           查看在线机组列表
- /flight <ISFP/SkyLite> <呼号>     按呼号查特定机组详细信息

### EFB 网页

中文版：
- 气象查询：https://efb.dubhenexus.org/weather
- 机场资料：https://efb.dubhenexus.org/info
- 航图查询：https://efb.dubhenexus.org/charts
- 航路查询：https://efb.dubhenexus.org/routes
- 起降性能：https://efb.dubhenexus.org/performance

英文版（en）：
- 机场资料：https://efb.dubhenexus.org/en/info?icao=:icao
- 气象查询：https://efb.dubhenexus.org/en/weather?icao=:icao
- 航图（ChartFox）：https://efb.dubhenexus.org/en/charts?icao=:icao&provider=chartfox
- 航图（Jeppesen）：https://efb.dubhenexus.org/en/charts?icao=:icao&provider=jeppesen
- 航路查询：https://efb.dubhenexus.org/en/routes
- 起降性能：https://efb.dubhenexus.org/en/performance
- 航班追踪：https://efb.dubhenexus.org/flights（测试中，效果可能不太好）

当用户询问航图时，如果不确定应该引导至 ChartFox 还是 Jeppesen 来源，可询问用户偏好；
默认推荐 ChartFox（免费且覆盖较广）。

### 官网

https://www.dubhenexus.org

### 联系我们

- info@dubhenexus.org      一般查询
- support@dubhenexus.org   反馈 / 建议 / 投诉 / 支持
- dev@dubhenexus.org       开发组（非严重或特殊情况下不要主动联系）
- collab@dubhenexus.org    合作洽谈

### 数据 API（data.dubhenexus.org）

所有航空数据统一从 Dubhe Nexus 后端 API 获取，调用方式：

```
curl -s "https://data.dubhenexus.org/api/{path}"
```

可用接口一览：

| 接口路径 | 说明 | 备注 |
|----------|------|------|
| `/airport/:icao` | 机场基础信息（名称、跑道、坐标等） | |
| `/airport/metar/:icao` | METAR 实时观测气象 | |
| `/airport/taf/:icao` | TAF 航站预报 | |
| `/airport/atis/:icao` | ATIS 通播 | 仅 VHHH |
| `/airport/notam/:icao` | NOTAM 航行通告 | 仅 VHHH |
| `/flights/isfp` | ISFP 在线机组 | |
| `/flights/skylite` | SkyLite 在线机组 | |

用法示例：
- `curl -s "https://data.dubhenexus.org/api/airport/metar/VHHH"
-  `curl -s "https://data.dubhenexus.org/api/flights/isfp"
-  `curl -s "https://data.dubhenexus.org/api/airport/VHHH"

**严禁使用 aviationweather.gov、isfpapi.flyisfp.com 等外部 API**，全部通过 Dubhe Nexus 代理。
ATIS/NOTAM 仅 VHHH 有接口，数据可能为空是正常的，直接告知用户即可，不要尝试其他途径获取。

### 行为准则

1. 你是天枢互联 Dubhe Nexus 的航空助手，具备专业的航空数据查询与解读能力。
2. 只在群聊中有人明确询问航空相关问题时才介入回复，不要主动打断别人的对话。
3. 当用户表达的需求不够清晰时（例如只说"查天气"但没给 ICAO），简洁地询问补充信息，
   而不是一次抛出所有选项。
4. 回复时优先使用自然语言解读数据，提供清晰有用的信息；同时可以附上对应的 EFB 网页链接，
   方便用户自行查看更多细节。
5. 不要在本回复中机械地罗列所有服务和指令——这些已作为你的背景知识，
   只在用户问到时再调用相关能力。

### 自然语言查询

当用户 @你 询问以下类型的问题时，你可以直接回答：

- "香港国际机场ICAO代码是啥" → VHHH
- "香港国际机场metar" → METAR VHHH ...（直接给出报文）
  附带：详细页面 https://efb.dubhenexus.org/weather?icao=VHHH
- "ISFP在线航班" → 列出当前在线机组（呼号 + 航线）
- "查一下CSN1025" → 该机组的详细信息

你不需要引导用户再发一遍指令，而是直接在回复中给出答案。
"""


@register(
    "astrbot_plugin_dubhe_nexus_services",
    "Dubhe Nexus Innovation and Research Studio",
    "天枢互联服务集成：航空数据查询（METAR/TAF/ATIS/NOTAM/机场/气象）、"
    "在线机组查询（ISFP/SkyLite）、EFB 航图链接引导、知识注入",
    "2.0.0",
)
class DubheNexusServicesPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)

    # ══════════════════════════════════════════════════════════
    # 1. LLM 知识注入 & 航空数据恢复
    # ══════════════════════════════════════════════════════════

    @filter.on_llm_request(priority=100)
    async def inject_services_knowledge(self, event: AstrMessageEvent, req):
        # 知识注入
        if DUBHE_NEXUS_KNOWLEDGE not in req.system_prompt:
            req.system_prompt += "\n\n" + DUBHE_NEXUS_KNOWLEDGE

        # 恢复自然语言查询注入的航空数据（被 AngelHeart prompt 重写覆盖后恢复）
        aviation_data = getattr(event, "_dubhe_aviation_prompt", None)
        if aviation_data:
            req.prompt = aviation_data
            logger.info("已恢复航空查询数据到 LLM 请求")

    # ══════════════════════════════════════════════════════════
    # 2. API 通用方法
    # ══════════════════════════════════════════════════════════

    async def _fetch_json(self, path: str) -> dict:
        url = f"{API_BASE}{path}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _parse_text(event: AstrMessageEvent) -> tuple[str, str]:
        text = (event.message_str or "").strip()
        return text, text.lower()

    @staticmethod
    def _extract_icao(text: str) -> str | None:
        candidates = ICAO_PATTERN.findall(text.upper())
        routable = [c for c in candidates if c[0] in ROUTABLE_ICAO_PREFIXES]
        if routable:
            return routable[0]
        return candidates[0] if candidates else None

    # ══════════════════════════════════════════════════════════
    # 3. 航空数据指令：/airport /metar /taf /atis /notam /weather
    # ══════════════════════════════════════════════════════════

    @filter.command("airport")
    async def _airport(self, event: AstrMessageEvent):
        text, _ = self._parse_text(event)
        args = text.split()
        if len(args) < 2:
            yield event.plain_result("用法: /airport <ICAO代码>\n例如: /airport VHHH")
        else:
            icao = args[1].upper()
            try:
                data = await self._fetch_json(f"/airport/{icao}")
                yield event.plain_result(self._fmt_airport(data))
            except Exception as e:
                logger.error(f"机场查询失败 {icao}: {e}")
                yield event.plain_result(f"查询机场信息失败: {e}")
        event.should_call_llm(False)
        event.stop_event()

    @filter.command("metar")
    async def _metar(self, event: AstrMessageEvent):
        text, _ = self._parse_text(event)
        args = text.split()
        if len(args) < 2:
            yield event.plain_result("用法: /metar <ICAO代码>\n例如: /metar VHHH")
        else:
            icao = args[1].upper()
            try:
                data = await self._fetch_json(f"/airport/metar/{icao}")
                raw = self._raw_metar(data)
                yield event.plain_result(raw or json.dumps(data, ensure_ascii=False))
            except Exception as e:
                logger.error(f"METAR 查询失败 {icao}: {e}")
                yield event.plain_result(f"查询 METAR 失败: {e}")
        event.should_call_llm(False)
        event.stop_event()

    @filter.command("taf")
    async def _taf(self, event: AstrMessageEvent):
        text, _ = self._parse_text(event)
        args = text.split()
        if len(args) < 2:
            yield event.plain_result("用法: /taf <ICAO代码>\n例如: /taf VHHH")
        else:
            icao = args[1].upper()
            try:
                data = await self._fetch_json(f"/airport/taf/{icao}")
                raw = self._raw_taf(data)
                yield event.plain_result(raw or json.dumps(data, ensure_ascii=False))
            except Exception as e:
                logger.error(f"TAF 查询失败 {icao}: {e}")
                yield event.plain_result(f"查询 TAF 失败: {e}")
        event.should_call_llm(False)
        event.stop_event()

    @filter.command("atis")
    async def _atis(self, event: AstrMessageEvent):
        try:
            data = await self._fetch_json("/airport/atis/VHHH")
            formatted = self._fmt_atis(data)
            yield event.plain_result(formatted or "暂无 VHHH ATIS 数据")
        except Exception as e:
            logger.error(f"ATIS 查询失败: {e}")
            yield event.plain_result(f"查询 ATIS 失败: {e}")
        event.should_call_llm(False)
        event.stop_event()

    @filter.command("notam")
    async def _notam(self, event: AstrMessageEvent):
        try:
            data = await self._fetch_json("/airport/notam/VHHH")
            formatted = self._fmt_notam(data)
            yield event.plain_result(formatted or "暂无 VHHH NOTAM 数据")
        except Exception as e:
            logger.error(f"NOTAM 查询失败: {e}")
            yield event.plain_result(f"查询 NOTAM 失败: {e}")
        event.should_call_llm(False)
        event.stop_event()

    @filter.command("weather")
    async def _weather(self, event: AstrMessageEvent):
        text, _ = self._parse_text(event)
        args = text.split()
        icao = args[1].upper() if len(args) >= 2 else "VHHH"

        try:
            metar_data, taf_data = await self._fetch_json(
                f"/airport/metar/{icao}"
            ), await self._fetch_json(f"/airport/taf/{icao}")
        except Exception as e:
            logger.error(f"气象查询失败 {icao}: {e}")
            yield event.plain_result(f"查询气象数据失败: {e}")
            event.should_call_llm(False)
            event.stop_event()
            return

        metar_raw = self._raw_metar(metar_data)
        taf_raw = self._raw_taf(taf_data)
        metar_decoded = self._decode_metar(metar_data)
        taf_decoded = self._decode_taf(taf_data)

        prompt = (
            f"用户查询了 {icao} 的气象数据，以下是实时航空天气信息：\n\n"
            "=== METAR（实时观测） ===\n"
            f"{metar_decoded}\n\n"
            "=== TAF（预报） ===\n"
            f"{taf_decoded}\n"
        )
        if metar_raw:
            prompt += f"\n=== METAR 原始报文 ===\n{metar_raw}\n"
        if taf_raw:
            prompt += f"\n=== TAF 原始报文 ===\n{taf_raw}\n"

        yield event.request_llm(
            prompt=prompt,
            system_prompt=(
                "你是一个专业的航空天气助手。请基于提供的实时气象数据，"
                "用自然语言向用户解读当前机场的天气状况和预报。"
                "请把天气现象代码（如 TSRA=雷暴伴雨、SHRA=阵雨、BR=轻雾）翻译成中文，"
                "并说明是否对飞行有影响。回复应简洁清晰，控制在300字以内。"
            ),
        )
        event._dubhe_aviation_prompt = prompt
        event.should_call_llm(False)
        event.stop_event()

    # ══════════════════════════════════════════════════════════
    # 4. 自然语言航空查询
    # ══════════════════════════════════════════════════════════

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE
        | filter.EventMessageType.PRIVATE_MESSAGE
        | filter.EventMessageType.FRIEND_MESSAGE,
        priority=-20,
    )
    async def _handle_natural_query(self, event: AstrMessageEvent):
        text, text_lower = self._parse_text(event)
        if not text or text.startswith("/"):
            return

        matched = [kw for kw in AVIATION_KEYWORDS if kw in text_lower]
        if not matched:
            return

        icao = self._extract_icao(text)

        # ATIS / NOTAM 没有 ICAO 时默认 VHHH（仅 VHHH 有数据源）
        needs_vhhh_only = any(kw in text_lower for kw in ("atis", "notam"))
        if not icao and needs_vhhh_only:
            icao = "VHHH"

        if not icao:
            return

        logger.info(f"自然语言航空查询: keywords={matched}, icao={icao}")

        try:
            if "notam" in text_lower:
                data = await self._fetch_json(f"/airport/notam/{icao}")
                raw = self._fmt_notam(data)
                label, hint = "NOTAM", "航行通告"
                if not raw:
                    yield event.plain_result(f"暂无 {icao} 的 NOTAM 数据。目前 NOTAM 仅支持 VHHH。")
                    event.should_call_llm(False)
                    event.stop_event()
                    return
            elif "atis" in text_lower:
                data = await self._fetch_json(f"/airport/atis/{icao}")
                raw = self._fmt_atis(data)
                label, hint = "ATIS", "自动终端信息"
                if not raw:
                    yield event.plain_result(f"暂无 {icao} 的 ATIS 数据。目前 ATIS 仅支持 VHHH。")
                    event.should_call_llm(False)
                    event.stop_event()
                    return
            elif "taf" in text_lower:
                data = await self._fetch_json(f"/airport/taf/{icao}")
                raw = self._decode_taf(data)
                label, hint = "TAF", "天气预报"
            elif any(kw in text_lower for kw in ("气象", "天气", "weather")):
                raw = await self._fetch_combined_weather(icao)
                label, hint = "气象", "天气报告"
            elif any(kw in text_lower for kw in ("机场", "airport", "跑道", "runway")):
                data = await self._fetch_json(f"/airport/{icao}")
                raw = self._fmt_airport(data)
                label, hint = "机场", "机场信息"
            else:
                data = await self._fetch_json(f"/airport/metar/{icao}")
                raw = self._decode_metar(data)
                label, hint = "METAR", "实时天气"

            if not raw:
                return

            yield event.request_llm(
                prompt=(
                    f"用户查询了 {icao} 的{hint}，以下是实时数据：\n\n"
                    f"=== {icao} {label} ===\n{raw}"
                ),
                system_prompt=(
                    "用户查询了航空气象/情报信息，"
                    "以下是实时API返回的数据。请用自然语言清晰地向用户解释这些数据，"
                    "包括关键的天气条件、风力、能见度、云层情况以及飞行注意事项。"
                    "请把天气现象代码翻译成中文。回复简洁明了，控制在300字以内。"
                ),
            )
            event._dubhe_aviation_prompt = (
                f"用户查询了 {icao} 的{hint}，以下是实时数据：\n\n"
                f"=== {icao} {label} ===\n{raw}"
            )
            event.should_call_llm(False)
            event.stop_event()
        except Exception as e:
            logger.error(f"自然语言查询处理失败: {e}")

    async def _fetch_combined_weather(self, icao: str) -> str:
        lines = []
        try:
            metar_data = await self._fetch_json(f"/airport/metar/{icao}")
            lines.append(self._decode_metar(metar_data))
        except Exception as e:
            lines.append(f"METAR 获取失败: {e}")

        try:
            taf_data = await self._fetch_json(f"/airport/taf/{icao}")
            lines.append(self._decode_taf(taf_data))
        except Exception as e:
            lines.append(f"TAF 获取失败: {e}")

        return "\n\n".join(lines)

    # ══════════════════════════════════════════════════════════
    # 5. /flight 指令
    # ══════════════════════════════════════════════════════════

    @filter.command("flight")
    async def _flight(self, event: AstrMessageEvent):
        text, _ = self._parse_text(event)
        parts = text.split()

        if len(parts) < 2:
            yield event.plain_result(
                "用法：\n"
                "/flight <平台>              查看所有在线机组\n"
                "/flight <平台> <呼号>        查找特定机组\n\n"
                "支持平台：ISFP、SkyLite\n"
                "例如：/flight ISFP\n"
                "例如：/flight ISFP CSN1025"
            )
            event.should_call_llm(False)
            event.stop_event()
            return

        platform = parts[1].lower()
        if platform not in COMMAND_PLATFORMS:
            yield event.plain_result(f"不支持的平台「{platform}」，当前仅支持 ISFP 和 SkyLite。")
            event.should_call_llm(False)
            event.stop_event()
            return

        callsign = parts[2].upper() if len(parts) >= 3 else None

        try:
            raw_data = await self._fetch_json(f"/flights/{platform}")
        except Exception as e:
            logger.error(f"航班查询失败 platform={platform}: {e}")
            yield event.plain_result(f"查询在线机组失败：{e}")
            event.should_call_llm(False)
            event.stop_event()
            return

        clients = self._extract_clients(raw_data, platform)
        if not clients:
            yield event.plain_result(f"当前 {platform.upper()} 暂无在线机组。")
            event.should_call_llm(False)
            event.stop_event()
            return

        if callsign:
            matched = self._match_clients(clients, callsign)
            if not matched:
                yield event.plain_result(f"未找到呼号为「{callsign}」的在线机组。")
                event.should_call_llm(False)
                event.stop_event()
                return

            if len(matched) == 1:
                result = self._fmt_flight_detail(matched[0], platform)
            else:
                result = self._fmt_flight_list(matched, platform)

            yield event.plain_result(result)
        else:
            total = len(clients)
            max_show = 40
            shown = clients[:max_show]
            result = self._fmt_flight_list(shown, platform)
            if total > max_show:
                result += (
                    f"\n\n（当前共 {total} 个在线机组，仅展示前 {max_show} 个。"
                    f"使用 /flight {platform} <呼号> 查找特定机组）"
                )
            yield event.plain_result(result)

        event.should_call_llm(False)
        event.stop_event()

    # ══════════════════════════════════════════════════════════
    # 6. 航班数据解析
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _extract_clients(data: dict | list, platform: str) -> list[dict]:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []

        if platform == "skylite":
            pilots = data.get("pilots") or data.get("clients") or []
            return pilots if isinstance(pilots, list) else []

        for key in ("clients", "pilots", "flights", "data"):
            val = data.get(key)
            if isinstance(val, list):
                return val
        return []

    @staticmethod
    def _match_clients(clients: list[dict], callsign: str) -> list[dict]:
        cs_upper = callsign.upper()
        exact = [c for c in clients if (c.get("callsign") or "").upper() == cs_upper]
        if exact:
            return exact
        return [c for c in clients if cs_upper in (c.get("callsign") or "").upper()]

    @staticmethod
    def _fmt_flight_list(clients: list[dict], platform: str) -> str:
        label = {"isfp": "ISFP", "skylite": "SkyLite"}.get(platform, platform.upper())
        lines = [f"{label} 在线机组", ""]
        for c in clients:
            cs = c.get("callsign") or "?"
            dep, arr = DubheNexusServicesPlugin._get_route(c, platform)
            route = f"{dep} → {arr}" if dep and arr else (dep or arr or "")
            line = cs
            if route:
                line += f"  {route}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _fmt_flight_detail(client: dict, platform: str) -> str:
        cs = client.get("callsign") or "?"
        name = (client.get("name") or client.get("sender_name")
                or client.get("pilot_name") or "")
        dep, arr = DubheNexusServicesPlugin._get_route(client, platform)
        lat = client.get("latitude") or client.get("lat")
        lon = client.get("longitude") or client.get("lon") or client.get("lng")
        alt = client.get("altitude") or client.get("alt")
        gs = client.get("groundspeed") or client.get("gs") or client.get("speed")
        hdg = client.get("heading") or client.get("hdg")
        sq = client.get("squawk_code") or client.get("squawk") or client.get("transponder") or ""
        cru_alt = client.get("cruise_altitude") or client.get("cruise_alt")
        cru_tas = client.get("cruise_tas") or client.get("cruise_speed")
        route = client.get("route") or client.get("flight_plan_route") or ""

        fp = client.get("flight_plan")
        if isinstance(fp, dict):
            if not cru_alt:
                cru_alt = fp.get("altitude")
            if not cru_tas:
                cru_tas = fp.get("cruise_tas")
            if not route:
                route = fp.get("route")

        lines = [cs]
        if name:
            lines.append(name)
        if dep or arr:
            lines.append(f"{dep or '?'} → {arr or '?'}")
        if lat is not None and lon is not None:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                lat_dir = "N" if lat_f >= 0 else "S"
                lon_dir = "E" if lon_f >= 0 else "W"
                lines.append(f"{abs(lat_f):.4f}°{lat_dir}  {abs(lon_f):.4f}°{lon_dir}")
            except (ValueError, TypeError):
                lines.append(f"{lat}  {lon}")

        status_parts = []
        if alt is not None and str(alt).strip():
            try:
                a = int(float(alt))
                status_parts.append(f"FL{a // 100}" if a > 100 else f"高度 {a} ft")
            except (ValueError, TypeError):
                status_parts.append(str(alt))
        if gs is not None and str(gs).strip():
            try:
                status_parts.append(f"地速 {int(float(gs))} kt")
            except (ValueError, TypeError):
                status_parts.append(f"{gs}")
        if hdg is not None and str(hdg).strip():
            try:
                status_parts.append(f"航向 {int(float(hdg))}°")
            except (ValueError, TypeError):
                status_parts.append(f"{hdg}")
        if status_parts:
            lines.append("  ".join(status_parts))

        if sq and str(sq).strip():
            lines.append(f"应答机 {sq}")

        cruise_parts = []
        if cru_alt is not None and str(cru_alt).strip():
            try:
                ca = int(float(cru_alt))
                cruise_parts.append(f"巡航高度 FL{ca // 100}" if ca > 100 else f"巡航高度 {ca} ft")
            except (ValueError, TypeError):
                cruise_parts.append(f"巡航高度 {cru_alt}")
        if cru_tas is not None and str(cru_tas).strip():
            try:
                cruise_parts.append(f"巡航速度 {int(float(cru_tas))} kt")
            except (ValueError, TypeError):
                cruise_parts.append(f"巡航速度 {cru_tas}")
        if cruise_parts:
            lines.append("  ".join(cruise_parts))

        if route and str(route).strip():
            lines.append("申报航线")
            lines.append(str(route).strip())

        return "\n".join(lines)

    @staticmethod
    def _get_route(client: dict, platform: str) -> tuple[str, str]:
        fp = client.get("flight_plan")
        if isinstance(fp, dict):
            dep = fp.get("departure") or ""
            arr = fp.get("arrival") or ""
            return dep, arr

        dep = client.get("departure_icao") or client.get("departure") or client.get("dep") or ""
        arr = client.get("arrival_icao") or client.get("arrival") or client.get("arr") or ""
        return dep, arr

    # ══════════════════════════════════════════════════════════
    # 7. 气象解码 & 格式化
    # ══════════════════════════════════════════════════════════

    cloud_cover = {
        "SKC": "晴空", "CLR": "晴朗", "FEW": "疏云",
        "SCT": "散云", "BKN": "多云", "OVC": "阴",
        "NSC": "无显著云", "VV": "垂直能见度不佳",
    }

    wx_codes = {
        "TS": "雷暴", "RA": "雨", "SN": "雪", "DZ": "毛毛雨",
        "SH": "阵性", "FG": "雾", "BR": "轻雾", "HZ": "霾",
        "FU": "烟", "DU": "浮尘", "SA": "沙", "GR": "冰雹",
        "GS": "小冰雹", "PL": "冰粒", "IC": "冰针", "SG": "米雪",
        "FZ": "冻", "SQ": "飑", "FC": "漏斗云", "SS": "沙尘暴",
        "DS": "尘暴", "VA": "火山灰", "PO": "尘卷风",
        "UP": "未知降水", "PY": "水沫",
    }

    def _decode_wx(self, wx_str: str | None) -> str:
        if not wx_str:
            return ""
        parts = wx_str.split()
        decoded = []
        for p in parts:
            code = p
            intensity = ""
            if code.startswith("-"):
                intensity = "弱"
                code = code[1:]
            elif code.startswith("+"):
                intensity = "强"
                code = code[1:]
            proximity = ""
            if code.startswith("VC"):
                proximity = "附近"
                code = code[2:]
            main = self.wx_codes.get(code, code)
            decoded.append(f"{proximity}{intensity}{main}")
        return "、".join(decoded)

    def _decode_metar(self, data: dict) -> str:
        metar = data.get("metar")
        if not isinstance(metar, dict):
            return str(metar) if metar else ""
        raw = metar.get("rawMETAR") or ""
        lines = []
        if raw:
            lines.append(f"原始报文: {raw}")
        if metar.get("obsTime"):
            ts = metar["obsTime"]
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            lines.append(f"观测时间: {dt.strftime('%Y-%m-%d %H:%M UTC')}")

        temp = metar.get("temp")
        dewp = metar.get("dewp")
        if temp is not None and dewp is not None:
            lines.append(f"温度: {temp}°C / 露点: {dewp}°C")
        elif temp is not None:
            lines.append(f"温度: {temp}°C")

        wdir = metar.get("wdir")
        wspd = metar.get("wspd")
        if wdir is not None and wspd is not None:
            wdir_str = "不定" if wdir == "VRB" else f"{wdir}°"
            lines.append(f"风向风速: {wdir_str} {wspd}KT")

        vis = metar.get("visib")
        if vis:
            lines.append(f"能见度: {vis}")

        altim = metar.get("altim")
        if altim:
            lines.append(f"QNH: {altim} hPa")

        clouds = metar.get("clouds")
        if isinstance(clouds, list) and clouds:
            cloud_strs = []
            for c in clouds:
                cover = self.cloud_cover.get(c.get("cover", ""), c.get("cover", ""))
                base = c.get("base", "")
                cloud_strs.append(f"{cover} {base}ft" if base else cover)
            lines.append(f"云层: {' / '.join(cloud_strs)}")

        wx_str = metar.get("wxString")
        if wx_str:
            decoded = self._decode_wx(wx_str)
            lines.append(f"天气: {decoded}")

        flt_cat = metar.get("fltCat")
        if flt_cat:
            lines.append(f"飞行规则: {flt_cat}")

        return "\n".join(lines)

    def _decode_taf(self, data: dict) -> str:
        taf = data.get("taf")
        if not isinstance(taf, dict):
            return str(taf) if taf else ""
        raw = taf.get("rawTAF") or ""
        lines = []
        if raw:
            lines.append(f"原始报文: {raw}")
        if taf.get("issueTime"):
            lines.append(f"发布时间: {taf['issueTime'].replace('T', ' ').replace('.000Z', ' UTC')}")

        fcsts = taf.get("fcsts")
        if isinstance(fcsts, list):
            lines.append("\n分段预报:")
            for fc in fcsts:
                change = fc.get("fcstChange") or "BASE"
                label = {
                    "BASE": "基础", "TEMPO": "临时", "BECMG": "转变",
                    "FM": "新阶段", "PROB": "概率",
                }.get(change, change)
                parts = []
                if fc.get("timeFrom"):
                    tf = datetime.fromtimestamp(fc["timeFrom"], tz=timezone.utc).strftime("%m-%d %H:%M")
                    parts.append(tf)
                if fc.get("timeTo"):
                    tt = datetime.fromtimestamp(fc["timeTo"], tz=timezone.utc).strftime("%m-%d %H:%M")
                    parts.append(f"- {tt}")
                time_range = " ".join(parts) if parts else ""
                header = f"  [{label}] {time_range}" if time_range else f"  [{label}]"

                detail_parts = []
                wdir = fc.get("wdir")
                wspd = fc.get("wspd")
                if wdir is not None and wspd is not None:
                    wdir_s = "不定" if wdir == "VRB" else f"{wdir}°"
                    detail_parts.append(f"{wdir_s} {wspd}KT")
                    if fc.get("wgst"):
                        detail_parts.append(f"阵风{fc['wgst']}KT")
                vis = fc.get("visib")
                if vis:
                    detail_parts.append(f"能见度 {vis}")
                wx = fc.get("wxString")
                if wx:
                    detail_parts.append(self._decode_wx(wx))
                clouds = fc.get("clouds")
                if isinstance(clouds, list) and clouds:
                    cloud_s = " / ".join(
                        f"{self.cloud_cover.get(c.get('cover',''), c.get('cover',''))} {c.get('base','')}ft"
                        for c in clouds
                    )
                    detail_parts.append(cloud_s)
                header += " " + " | ".join(detail_parts) if detail_parts else ""
                lines.append(header)

        return "\n".join(lines)

    @staticmethod
    def _raw_metar(data: dict) -> str:
        metar = data.get("metar")
        if isinstance(metar, dict):
            return metar.get("rawMETAR", "")
        return ""

    @staticmethod
    def _raw_taf(data: dict) -> str:
        taf = data.get("taf")
        if isinstance(taf, dict):
            return taf.get("rawTAF", "")
        return ""

    @staticmethod
    def _fmt_airport(data: dict) -> str:
        raw = data.get("data")
        if not isinstance(raw, dict):
            return str(raw) if raw else json.dumps(data, ensure_ascii=False)

        lines = []
        name = raw.get("name", "N/A")
        if raw.get("iataId"):
            name += f" ({raw['iataId']})"
        lines.append(f"{name}")

        loc_parts = [p for p in [raw.get("state"), raw.get("country")] if p]
        loc = raw.get("icaoId", "N/A")
        if loc_parts:
            loc += f" | {'/'.join(loc_parts)}"
        lines.append(loc)

        coord = f"{raw.get('lat', '?')}, {raw.get('lon', '?')}"
        if raw.get("elev") is not None:
            coord += f" | 海拔 {raw['elev']}ft"
        if raw.get("magdec"):
            coord += f" | 磁差 {raw['magdec']}"
        lines.append(coord)

        rwy_parts = []
        if raw.get("rwyNum"):
            rwy_parts.append(f"{raw['rwyNum']}条")
        if raw.get("rwyLength"):
            rwy_parts.append(raw["rwyLength"])
        rwy_line = f"跑道: {' '.join(rwy_parts)}" if rwy_parts else "跑道:"
        if raw.get("runways"):
            for r in raw["runways"]:
                rwy_line += (
                    f"\n  {r['id']} ({r['lengthM']}m x {r['widthM']}m, {r['surface']})"
                )
        lines.append(rwy_line)

        if raw.get("rawMETAR"):
            lines.append(f"\n最新 METAR:\n{raw['rawMETAR']}")
        if raw.get("rawTAF"):
            lines.append(f"\n最新 TAF:\n{raw['rawTAF']}")

        return "\n".join(lines)

    @staticmethod
    def _fmt_atis(data: dict) -> str:
        lines = []
        for key in ("arrival", "departure"):
            info = data.get(key)
            if isinstance(info, dict) and info.get("raw"):
                label = "进近" if key == "arrival" else "离场"
                lines.append(f"=== {label} ATIS ===\n{info['raw']}")
        return "\n\n".join(lines)

    @staticmethod
    def _fmt_notam(data: dict) -> str:
        notams = data.get("notams")
        if isinstance(notams, list):
            lines = []
            for i, n in enumerate(notams, 1):
                if isinstance(n, dict) and n.get("content"):
                    lines.append(f"=== NOTAM #{i} ===\n{n['content']}")
            return "\n\n".join(lines) if lines else ""
        return ""

    # ══════════════════════════════════════════════════════════
    # 8. 卸载
    # ══════════════════════════════════════════════════════════

    async def terminate(self):
        logger.info("Dubhe Nexus Services 插件已卸载")
