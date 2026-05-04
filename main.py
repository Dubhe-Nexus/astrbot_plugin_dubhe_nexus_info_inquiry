from __future__ import annotations

import json
import logging
import re

import httpx
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

logger = logging.getLogger(__name__)

API_BASE = "https://data.dubhenexus.org/api"
AVIATION_KEYWORDS = ["metar", "taf", "atis", "notam", "meter"]
ICAO_PATTERN = re.compile(r"\b[A-Z]{4}\b")


@register(
    "astrbot_plugin_dubhe_nexus_info_inquiry",
    "Dubhe Nexus Innovation and Research Studio",
    "航空数据查询：机场信息、METAR、TAF、ATIS、NOTAM",
    "1.1.0",
)
class DubheNexusAviationPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self._recent_api_data: dict[str, str] = {}

    async def _fetch_json(self, path: str) -> dict:
        url = f"{API_BASE}{path}"
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _parse_args(event: AstrMessageEvent) -> list[str]:
        return (event.message_str or "").strip().split()

    @staticmethod
    def _extract_icao(text: str) -> str | None:
        matches = ICAO_PATTERN.findall(text.upper())
        for m in matches:
            if m[0] in "VZRPYOBG":
                return m
        return matches[0] if matches else None

    @filter.on_llm_request(priority=-5000)
    async def _inject_api_context(
        self, event: AstrMessageEvent, req: ProviderRequest
    ):
        session_id = event.unified_msg_origin
        if session_id in self._recent_api_data:
            data = self._recent_api_data.pop(session_id)
            system_msg = {
                "role": "system",
                "content": (
                    "以下是为该用户查询到的最近实时航空数据，"
                    "如果用户后续提问与此相关，请基于此数据回答：\n"
                    f"{data}"
                ),
            }
            if req.contexts:
                req.contexts.insert(0, system_msg)
            else:
                req.contexts = [system_msg]

    @filter.command("airport")
    async def _airport(self, event: AstrMessageEvent):
        args = self._parse_args(event)
        if len(args) < 2:
            yield event.plain_result("用法: /airport <ICAO代码>\n例如: /airport VHHH")
            event.should_call_llm(False)
            event.stop_event()
            return
        icao = args[1].upper()
        try:
            data = await self._fetch_json(f"/airport/{icao}")
            formatted = self._format_airport(data)
            self._recent_api_data[event.unified_msg_origin] = formatted
            yield event.plain_result(formatted)
        except Exception as e:
            logger.error(f"查询机场信息失败: {e}")
            yield event.plain_result(f"查询机场信息失败: {e}")
        finally:
            event.should_call_llm(False)
            event.stop_event()

    @filter.command("metar")
    async def _metar(self, event: AstrMessageEvent):
        args = self._parse_args(event)
        if len(args) < 2:
            yield event.plain_result("用法: /metar <ICAO代码>\n例如: /metar VHHH")
            event.should_call_llm(False)
            event.stop_event()
            return
        icao = args[1].upper()
        try:
            data = await self._fetch_json(f"/airport/metar/{icao}")
            formatted = self._format_metar(data)
            if formatted:
                self._recent_api_data[event.unified_msg_origin] = formatted
                yield event.plain_result(formatted)
            else:
                yield event.plain_result(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"查询 METAR 失败: {e}")
            yield event.plain_result(f"查询 METAR 失败: {e}")
        finally:
            event.should_call_llm(False)
            event.stop_event()

    @filter.command("taf")
    async def _taf(self, event: AstrMessageEvent):
        args = self._parse_args(event)
        if len(args) < 2:
            yield event.plain_result("用法: /taf <ICAO代码>\n例如: /taf VHHH")
            event.should_call_llm(False)
            event.stop_event()
            return
        icao = args[1].upper()
        try:
            data = await self._fetch_json(f"/airport/taf/{icao}")
            formatted = self._format_taf(data)
            if formatted:
                self._recent_api_data[event.unified_msg_origin] = formatted
                yield event.plain_result(formatted)
            else:
                yield event.plain_result(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"查询 TAF 失败: {e}")
            yield event.plain_result(f"查询 TAF 失败: {e}")
        finally:
            event.should_call_llm(False)
            event.stop_event()

    @filter.command("atis")
    async def _atis(self, event: AstrMessageEvent):
        args = self._parse_args(event)
        if len(args) >= 2:
            icao = args[1].upper()
            if icao != "VHHH":
                yield event.plain_result("目前仅支持香港国际机场(VHHH)的ATIS查询。\n用法: /atis")
                event.should_call_llm(False)
                event.stop_event()
                return
        try:
            data = await self._fetch_json("/airport/atis/VHHH")
            formatted = self._format_atis(data)
            if formatted:
                self._recent_api_data[event.unified_msg_origin] = formatted
                yield event.plain_result(formatted)
            else:
                yield event.plain_result(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"查询 ATIS 失败: {e}")
            yield event.plain_result(f"查询 ATIS 失败: {e}")
        finally:
            event.should_call_llm(False)
            event.stop_event()

    @filter.command("notam")
    async def _notam(self, event: AstrMessageEvent):
        args = self._parse_args(event)
        if len(args) >= 2:
            icao = args[1].upper()
            if icao != "VHHH":
                yield event.plain_result("目前仅支持香港国际机场(VHHH)的NOTAM查询。\n用法: /notam")
                event.should_call_llm(False)
                event.stop_event()
                return
        try:
            data = await self._fetch_json("/airport/notam/VHHH")
            formatted = self._format_notam(data)
            if formatted:
                self._recent_api_data[event.unified_msg_origin] = formatted
                yield event.plain_result(formatted)
            else:
                yield event.plain_result(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"查询 NOTAM 失败: {e}")
            yield event.plain_result(f"查询 NOTAM 失败: {e}")
        finally:
            event.should_call_llm(False)
            event.stop_event()

    # ── 自然语言查询检测 ─────────────────────────────────

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE
        | filter.EventMessageType.PRIVATE_MESSAGE
        | filter.EventMessageType.FRIEND_MESSAGE,
        priority=60,
    )
    async def _handle_natural_query(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip().lower()
        if not text or text.startswith("/"):
            return

        matched = [kw for kw in AVIATION_KEYWORDS if kw in text]
        if not matched:
            return

        icao = self._extract_icao(text)
        if not icao:
            return

        logger.info(f"检测到自然语言航空查询: keywords={matched}, icao={icao}")

        try:
            text_lower = text
            if "notam" in text_lower:
                data = await self._fetch_json(f"/airport/notam/{icao}")
                formatted = self._format_notam(data)
                label = f"{icao} NOTAM"
            elif "atis" in text_lower:
                data = await self._fetch_json(f"/airport/atis/{icao}")
                formatted = self._format_atis(data)
                label = f"{icao} ATIS"
            elif "taf" in text_lower:
                data = await self._fetch_json(f"/airport/taf/{icao}")
                formatted = self._format_taf(data)
                label = f"{icao} TAF"
            else:
                data = await self._fetch_json(f"/airport/metar/{icao}")
                formatted = self._format_metar(data)
                label = f"{icao} METAR"

            if not formatted:
                return

            yield event.request_llm(
                prompt=(
                    f"用户提到了航空查询关键词，已自动调用API获取到{label}的实时数据。\n"
                    f"请基于以下数据回答用户，并用自然语言解释其中的关键信息：\n\n"
                    f"{formatted}"
                ),
                system_prompt=(
                    "你是一个航空数据助手。用户问到了航空气象/情报信息，"
                    "以下是实时API返回的数据，请用自然语言向用户解释这些数据，"
                    "包括关键的气象条件、飞行注意事项等。"
                ),
            )

            event.should_call_llm(False)
            event.stop_event()

        except Exception as e:
            logger.error(f"自然语言航空查询处理失败: {e}")

    # ── 格式化工具 ────────────────────────────────────────

    @staticmethod
    def _format_airport(data: dict) -> str:
        raw = data.get("data")
        if not isinstance(raw, dict):
            return str(raw) if raw else json.dumps(data, ensure_ascii=False)

        lines = []
        name = raw.get("name", "N/A")
        if raw.get("iataId"):
            name += f" ({raw['iataId']})"
        lines.append(name)

        loc_parts = [p for p in [raw.get("state"), raw.get("country")] if p]
        loc = raw.get("icaoId", "N/A")
        if loc_parts:
            loc += f" | {'/'.join(loc_parts)}"
        lines.append(loc)

        coord = f"{raw.get('lat', '?')}, {raw.get('lon', '?')}"
        if raw.get("elev") is not None:
            coord += f" | {raw['elev']}ft"
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
                    f"\n  {r['id']} ({r['lengthM']}mx{r['widthM']}m, {r['surface']})"
                )
        lines.append(rwy_line)

        if raw.get("rawMETAR"):
            lines.append(f"\nMETAR:\n{raw['rawMETAR']}")
        if raw.get("rawTAF"):
            lines.append(f"\nTAF:\n{raw['rawTAF']}")

        return "\n".join(lines)

    @staticmethod
    def _format_metar(data: dict) -> str:
        metar = data.get("metar")
        if isinstance(metar, dict) and metar.get("rawMETAR"):
            return metar["rawMETAR"]
        return ""

    @staticmethod
    def _format_taf(data: dict) -> str:
        taf = data.get("taf")
        if isinstance(taf, dict) and taf.get("rawTAF"):
            return taf["rawTAF"]
        return ""

    @staticmethod
    def _format_atis(data: dict) -> str:
        lines = []
        arrival = data.get("arrival")
        departure = data.get("departure")
        if arrival and arrival.get("raw"):
            lines.append(arrival["raw"])
        if departure and departure.get("raw"):
            lines.append(departure["raw"])
        return "\n\n".join(lines)

    @staticmethod
    def _format_notam(data: dict) -> str:
        notams = data.get("notams")
        if notams:
            lines = [n.get("content", "") for n in notams if n.get("content")]
            return "\n\n".join(lines)
        return ""
