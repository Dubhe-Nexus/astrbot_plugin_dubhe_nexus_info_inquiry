from __future__ import annotations

import json
import logging

import httpx
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

logger = logging.getLogger(__name__)

API_BASE = "https://data.dubhenexus.org/api"

AVIATION_KEYWORDS = [
    "metar", "taf", "atis", "notam"
]

import re

ICAO_PATTERN = re.compile(r"\b([A-Za-z]{4})\b")

ROUTABLE_ICAO_PREFIXES = frozenset("VZRPYOBG")


@register(
    "astrbot_plugin_dubhe_nexus_info_inquiry",
    "Dubhe Nexus Innovation and Research Studio",
    "航空数据与气象查询：机场信息、METAR、TAF、ATIS、NOTAM",
    "2.0.0",
)
class DubheNexusAviationPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)

    # ── HTTP 工具 ────────────────────────────────────────

    async def _fetch_json(self, path: str) -> dict:
        url = f"{API_BASE}{path}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    # ── 参数解析 ─────────────────────────────────────────

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

    # ── 指令处理器 ───────────────────────────────────────

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
                yield event.plain_result(f"❌ 查询机场信息失败: {e}")
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
                yield event.plain_result(f"❌ 查询 METAR 失败: {e}")
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
                yield event.plain_result(f"❌ 查询 TAF 失败: {e}")
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
            yield event.plain_result(f"❌ 查询 ATIS 失败: {e}")
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
            yield event.plain_result(f"❌ 查询 NOTAM 失败: {e}")
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
            yield event.plain_result(f"❌ 查询气象数据失败: {e}")
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
        event.should_call_llm(False)
        event.stop_event()

    # ── 自然语言查询 ─────────────────────────────────────

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE
        | filter.EventMessageType.PRIVATE_MESSAGE
        | filter.EventMessageType.FRIEND_MESSAGE,
        priority=60,
    )
    async def _handle_natural_query(self, event: AstrMessageEvent):
        text, text_lower = self._parse_text(event)
        if not text or text.startswith("/"):
            return

        matched = [kw for kw in AVIATION_KEYWORDS if kw in text_lower]
        if not matched:
            return

        icao = self._extract_icao(text)
        if not icao:
            return

        logger.info(f"自然语言航空查询: keywords={matched}, icao={icao}")

        try:
            if "notam" in text_lower:
                data = await self._fetch_json(f"/airport/notam/{icao}")
                raw = self._fmt_notam(data)
                label, hint = "NOTAM", "航行通告"
            elif "atis" in text_lower:
                data = await self._fetch_json(f"/airport/atis/{icao}")
                raw = self._fmt_atis(data)
                label, hint = "ATIS", "自动终端信息"
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
                label, hint = "METAR", "实时观测"

            if not raw:
                return

            yield event.request_llm(
                prompt=(
                    f"用户查询了 {icao} 的{hint}，以下是实时数据：\n\n"
                    f"=== {icao} {label} ===\n{raw}"
                ),
                system_prompt=(
                    "你是一个航空数据助手。用户查询了航空气象/情报信息，"
                    "以下是实时API返回的数据。请用自然语言清晰地向用户解释这些数据，"
                    "包括关键的天气条件、风力、能见度、云层情况以及飞行注意事项。"
                    "请把天气现象代码翻译成中文。回复简洁明了，控制在300字以内。"
                ),
            )
            event.should_call_llm(False)
            event.stop_event()
        except Exception as e:
            logger.error(f"自然语言查询处理失败: {e}")

    # ── 气象数据聚合 ─────────────────────────────────────

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

    # ── 气象解码 ─────────────────────────────────────────

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
            from datetime import datetime, timezone
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
            from datetime import datetime, timezone
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

    # ── 原始报文提取 ─────────────────────────────────────

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

    # ── 格式化工具 ────────────────────────────────────────

    @staticmethod
    def _fmt_airport(data: dict) -> str:
        raw = data.get("data")
        if not isinstance(raw, dict):
            return str(raw) if raw else json.dumps(data, ensure_ascii=False)

        lines = []
        name = raw.get("name", "N/A")
        if raw.get("iataId"):
            name += f" ({raw['iataId']})"
        lines.append(f"📍 {name}")

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
                    f"\n  {r['id']} ({r['lengthM']}m × {r['widthM']}m, {r['surface']})"
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
                label = "进港" if key == "arrival" else "离港"
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
