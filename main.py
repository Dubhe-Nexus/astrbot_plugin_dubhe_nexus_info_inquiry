from __future__ import annotations

import json
import logging

import httpx
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

logger = logging.getLogger(__name__)

API_BASE = "https://data.dubhenexus.org/api"


@register("astrbot_plugin_dubhe_nexus_info_inquiry", "Dubhe Nexus Innovation and Research Studio", "航空数据查询：机场信息、METAR、TAF、ATIS、NOTAM", "1.0.0")
class DubheNexusAviationPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)

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
    def _disable_ai_and_cache(event: AstrMessageEvent):
        event.should_call_llm(False)
        event.stop_event()

    @staticmethod
    def _parse_args(event: AstrMessageEvent) -> list[str]:
        return (event.message_str or "").strip().split()

    @filter.command("airport")
    async def _airport(self, event: AstrMessageEvent):
        self._disable_ai_and_cache(event)
        args = self._parse_args(event)
        if len(args) < 2:
            yield event.plain_result("用法: /airport <ICAO代码>\n例如: /airport VHHH")
            return
        icao = args[1].upper()
        try:
            data = await self._fetch_json(f"/airport/{icao}")
            raw_data = data.get("data")
            if isinstance(raw_data, dict):
                lines = []
                if raw_data.get("rawMETAR"):
                    lines.append(raw_data["rawMETAR"])
                if raw_data.get("rawTAF"):
                    lines.append(raw_data["rawTAF"])
                if lines:
                    yield event.plain_result("\n\n".join(lines))
                else:
                    yield event.plain_result(json.dumps(raw_data, ensure_ascii=False))
            else:
                yield event.plain_result(str(raw_data) if raw_data else json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"查询机场信息失败: {e}")
            yield event.plain_result(f"查询机场信息失败: {e}")

    @filter.command("metar")
    async def _metar(self, event: AstrMessageEvent):
        self._disable_ai_and_cache(event)
        args = self._parse_args(event)
        if len(args) < 2:
            yield event.plain_result("用法: /metar <ICAO代码>\n例如: /metar VHHH")
            return
        icao = args[1].upper()
        try:
            data = await self._fetch_json(f"/airport/metar/{icao}")
            metar = data.get("metar")
            if isinstance(metar, dict) and metar.get("rawMETAR"):
                yield event.plain_result(metar["rawMETAR"])
            else:
                yield event.plain_result(str(metar) if metar else json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"查询 METAR 失败: {e}")
            yield event.plain_result(f"查询 METAR 失败: {e}")

    @filter.command("taf")
    async def _taf(self, event: AstrMessageEvent):
        self._disable_ai_and_cache(event)
        args = self._parse_args(event)
        if len(args) < 2:
            yield event.plain_result("用法: /taf <ICAO代码>\n例如: /taf VHHH")
            return
        icao = args[1].upper()
        try:
            data = await self._fetch_json(f"/airport/taf/{icao}")
            taf = data.get("taf")
            if isinstance(taf, dict) and taf.get("rawTAF"):
                yield event.plain_result(taf["rawTAF"])
            else:
                yield event.plain_result(str(taf) if taf else json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"查询 TAF 失败: {e}")
            yield event.plain_result(f"查询 TAF 失败: {e}")

    @filter.command("atis")
    async def _atis(self, event: AstrMessageEvent):
        self._disable_ai_and_cache(event)
        args = self._parse_args(event)
        if len(args) >= 2:
            icao = args[1].upper()
            if icao != "VHHH":
                yield event.plain_result("目前仅支持香港国际机场的 ATIS 查询。\n用法: /atis")
                return
        try:
            data = await self._fetch_json("/airport/atis/VHHH")
            lines = []
            arrival = data.get("arrival")
            departure = data.get("departure")
            if arrival and arrival.get("raw"):
                lines.append(arrival["raw"])
            if departure and departure.get("raw"):
                lines.append(departure["raw"])
            yield event.plain_result("\n\n".join(lines) if lines else json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"查询 ATIS 失败: {e}")
            yield event.plain_result(f"查询 ATIS 失败: {e}")

    @filter.command("notam")
    async def _notam(self, event: AstrMessageEvent):
        self._disable_ai_and_cache(event)
        args = self._parse_args(event)
        if len(args) >= 2:
            icao = args[1].upper()
            if icao != "VHHH":
                yield event.plain_result("目前仅支持香港国际机场的 NOTAM 查询。\n用法: /notam")
                return
        try:
            data = await self._fetch_json("/airport/notam/VHHH")
            notams = data.get("notams")
            if notams:
                lines = [n.get("content", "") for n in notams if n.get("content")]
                yield event.plain_result("\n\n".join(lines))
            else:
                yield event.plain_result(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"查询 NOTAM 失败: {e}")
            yield event.plain_result(f"查询 NOTAM 失败: {e}")
