"""Small web results with bounded downloads and public-address-only page access."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from jarvis.tools.base import RISK_READ, Tool, ToolContext, ToolError, ToolResult, obj

MAX_PAGE_BYTES = 2 * 1024 * 1024


def _search(query: str) -> list[dict[str, str]]:
    from ddgs import DDGS

    return list(DDGS(timeout=12).text(query, max_results=5))


async def web_search(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    query = args["query"].strip()
    if not query:
        raise ToolError("Provide a search query.")
    try:
        found = await asyncio.to_thread(ctx.services.get("web_search") or _search, query)
    except Exception as exc:
        raise ToolError("Web search is unavailable or rate-limited. Try again later.") from exc
    lines: list[str] = []
    for item in found[:5]:
        url = str(item.get("href") or item.get("url") or "")
        if not url.startswith(("https://", "http://")) or len(url) > 400:
            continue
        remaining = 900 - sum(len(line) + 2 for line in lines)
        title = re.sub(r"\s+", " ", str(item.get("title", "Result")))[:55]
        line = f"{title}\n{url}"
        if len(line) > remaining:
            continue
        snippet = re.sub(r"\s+", " ", str(item.get("body") or item.get("snippet") or ""))[:max(0, min(90, remaining - len(line) - 1))]
        lines.append(line + ("\n" + snippet if snippet else ""))
    return ToolResult(True, "\n\n".join(lines) or "No search results were returned.", summary=f"Searched: {query}", untrusted=True)


def _resolve(host: str, port: int) -> list[str]:
    return list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))


def public_address(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return public_address(str(ip.ipv4_mapped))
        if ip.sixtofour or ip.teredo or "%" in value:
            return False
    return ip.is_global and not (ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified)


async def pinned_url(raw: str, ctx: ToolContext) -> tuple[httpx.URL, str, str]:
    try:
        url = httpx.URL(raw)
        if url.scheme not in ("http", "https") or not url.host or url.username or url.password:
            raise ValueError()
        port = url.port or (443 if url.scheme == "https" else 80)
        addresses = await asyncio.to_thread(ctx.services.get("page_resolver") or _resolve, url.host, port)
        if not addresses or not all(public_address(ip) for ip in addresses):
            raise ToolError("Page reading blocks private, local and reserved network addresses.")
        # Connect to the checked address, retaining the original Host and TLS name.
        # DNS cannot change between the check and the connection.
        return url.copy_with(host=addresses[0]), url.netloc.decode("ascii"), url.host
    except ToolError:
        raise
    except (ValueError, httpx.InvalidURL, OSError) as exc:
        raise ToolError("That web address could not be resolved. Use a public http or https URL.") from exc


class PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "svg", "template"):
            self.skip += 1
        if not self.skip and tag in ("p", "div", "br", "li", "h1", "h2", "h3", "tr", "section", "article"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg", "template") and self.skip:
            self.skip -= 1
        elif not self.skip and tag in ("p", "div", "li", "h1", "h2", "h3", "tr"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(line for chunk in "".join(self.parts).splitlines() if (line := " ".join(chunk.split())))


async def read_page(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    current = args["url"]
    try:
        # No environment proxy or automatic redirect can bypass address validation.
        async with httpx.AsyncClient(timeout=12, trust_env=False, follow_redirects=False,
                                     limits=httpx.Limits(max_keepalive_connections=0),
                                     transport=ctx.services.get("web_transport")) as client:
            for hop in range(6):
                target, host, tls_name = await pinned_url(current, ctx)
                async with client.stream("GET", target, headers={"Host": host, "Accept-Encoding": "identity", "User-Agent": "JARVIS/2.1 (page reader)"},
                                         extensions={"sni_hostname": tls_name}) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if hop == 5 or not response.headers.get("location"):
                            raise ToolError("The page redirects too many times or has an invalid redirect.")
                        current = urljoin(current, response.headers["location"])
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type not in ("text/html", "text/plain", "application/xhtml+xml"):
                        raise ToolError("This address does not return a readable HTML or text page.")
                    if response.headers.get("content-encoding", "identity").lower() not in ("identity", ""):
                        raise ToolError("This server insists on compressed data, which the bounded page reader cannot accept.")
                    length = response.headers.get("content-length", "")
                    if length.isdigit() and int(length) > MAX_PAGE_BYTES:
                        raise ToolError("This page is too large (limit 2 MB).")
                    data = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        data.extend(chunk)
                        if len(data) > MAX_PAGE_BYTES:
                            raise ToolError("This page is too large (limit 2 MB).")
                    encoding = response.encoding or "utf-8"
                    try:
                        source = bytes(data).decode(encoding, errors="replace")
                    except LookupError:
                        source = bytes(data).decode("utf-8", errors="replace")
                    break
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"The website returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise ToolError("The website could not be reached or timed out.") from exc
    if content_type == "text/plain":
        body = source
    else:
        parser = PageText()
        parser.feed(source)
        body = parser.text()
    words = re.findall(r"\w+", args.get("focus", "").casefold())
    if words:
        paragraphs = body.splitlines()
        matches = [line for line in paragraphs if any(word in line.casefold() for word in words)]
        if matches:
            body = "\n".join(matches)
    prefix = f"Source: {current[:500]}\n"
    allowance = 2800 - len(prefix)
    result = body[:allowance] or "No readable text was found; this page may need JavaScript or a login."
    return ToolResult(True, prefix + result, summary="Read web page", untrusted=True)


_WEATHER = {0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Freezing fog",
            51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
            71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers", 81: "Rain showers", 82: "Heavy showers",
            95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail"}


async def _weather_json(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    async with client.stream("GET", url, params=params) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=16384):
            data.extend(chunk)
            if len(data) > 200_000:
                raise ToolError("The weather service returned too much data.")
        return json.loads(data)


async def get_weather(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    place = args.get("place") or ctx.services["prefs"].all().get("home_city", "")
    if not place:
        raise ToolError("Provide a place, or set your home city in Settings.")
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False, transport=ctx.services.get("web_transport")) as client:
            geo = await _weather_json(client, "https://geocoding-api.open-meteo.com/v1/search", {"name": place, "count": 1, "language": "en"})
            if not geo.get("results"):
                raise ToolError("No matching place was found. Try including the country.")
            location = geo["results"][0]
            forecast = await _weather_json(client, "https://api.open-meteo.com/v1/forecast", {
                "latitude": location["latitude"], "longitude": location["longitude"], "timezone": "auto", "forecast_days": 1,
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
        now, daily = forecast["current"], forecast["daily"]
        timestamp = datetime.fromisoformat(now["time"]).strftime("%d %b, %I:%M %p").replace(" 0", " ")
        name = ", ".join(str(location.get(key, ""))[:80] for key in ("name", "admin1", "country") if location.get(key))
        text = (f"{name} — {timestamp} (local): {_WEATHER.get(now['weather_code'], 'Weather code ' + str(now['weather_code']))}.\n"
                f"{now['temperature_2m']} °C, feels like {now['apparent_temperature']} °C; wind {now['wind_speed_10m']} km/h.\n"
                f"Today: {daily['temperature_2m_min'][0]}–{daily['temperature_2m_max'][0]} °C; max rain chance {daily['precipitation_probability_max'][0]}%.\n"
                "Source: Open-Meteo (https://open-meteo.com/), CC BY 4.0.")
        return ToolResult(True, text[:1200], summary=f"Weather for {place}", untrusted=True)
    except ToolError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ToolError("Weather is unavailable or returned incomplete data. Try again later.") from exc


TOOLS = [
    Tool("web_search", "web", "Search the web", "Search the web; returns up to five sources.",
         obj({"query": {"type": "string", "maxLength": 200}}, ["query"]), RISK_READ, web_search,
         lambda a: f"Search: {a.get('query', '')}", untrusted_output=True),
    Tool("read_page", "web", "Read a web page", "Read a public web page; optional focus selects relevant paragraphs.",
         obj({"url": {"type": "string", "maxLength": 1000}, "focus": {"type": "string", "maxLength": 120}}, ["url"]),
         RISK_READ, read_page, lambda a: "Read web page", untrusted_output=True),
    Tool("get_weather", "web", "Get weather", "Current weather and today's forecast; defaults to home city.",
         obj({"place": {"type": "string", "maxLength": 100}}), RISK_READ, get_weather,
         lambda a: f"Weather: {a.get('place', 'home city')}", untrusted_output=True),
]
