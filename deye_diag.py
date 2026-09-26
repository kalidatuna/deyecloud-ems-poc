#!/usr/bin/env python3
"""Small DeyeCloud OpenAPI diagnostic client for a paid EMS PoC.

The tool is intentionally conservative: discovery/telemetry calls are read-only,
and arbitrary control calls are dry-run unless --execute is supplied explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit
from dataclasses import dataclass
from typing import Any, Callable


JsonDict = dict[str, Any]
PostFn = Callable[[str, JsonDict, dict[str, str]], JsonDict]
GetFn = Callable[[str, dict[str, str]], JsonDict]


def sha256_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest().lower()


def login_field(login: str) -> JsonDict:
    login = login.strip()
    if not login:
        raise ValueError("login cannot be empty")
    return {"email": login} if "@" in login else {"username": login}


def http_post_json(url: str, payload: JsonDict, headers: dict[str, str]) -> JsonDict:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error calling {url}: {exc.reason}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON response from {url}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"JSON response from {url} must be an object")
    return data


def http_get_json(url: str, headers: dict[str, str]) -> JsonDict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error calling {url}: {exc.reason}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON response from {url}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"JSON response from {url} must be an object")
    return data


@dataclass
class DeyeCloudClient:
    base_url: str
    app_id: str
    app_secret: str
    login: str
    password: str
    company_id: str | None = None
    post: PostFn = http_post_json
    get: GetFn = http_get_json
    token: str | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("base_url must be a plain HTTPS URL with a hostname")

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _auth_headers(self) -> dict[str, str]:
        if not self.token:
            raise RuntimeError("authenticate() must be called first")
        return {"Authorization": f"Bearer {self.token}"}

    def authenticate(self) -> str:
        payload: JsonDict = {
            "appSecret": self.app_secret,
            **login_field(self.login),
            "password": sha256_password(self.password),
        }
        if self.company_id:
            payload["companyId"] = self.company_id.strip()
        result = self.post(
            self._url(f"account/token?appId={quote(self.app_id, safe='')}"), payload, {}
        )
        if not result.get("success") or not result.get("accessToken"):
            raise RuntimeError(f"DeyeCloud token request failed: {result.get('msg', result)}")
        self.token = str(result["accessToken"])
        return self.token

    def stations(self) -> list[JsonDict]:
        result = self.post(self._url("station/list"), {}, self._auth_headers())
        if result.get("success") is False:
            raise RuntimeError(f"station list failed: {result.get('msg', result)}")
        return list(result.get("stationList") or [])

    def devices(self, station_ids: list[Any], page_size: int = 100) -> list[JsonDict]:
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ValueError("page_size must be a positive integer")
        if not station_ids:
            return []
        page = 1
        devices: list[JsonDict] = []
        while True:
            result = self.post(
                self._url("station/device"),
                {"page": page, "size": page_size, "stationIds": station_ids},
                self._auth_headers(),
            )
            if result.get("success") is False:
                raise RuntimeError(f"device discovery failed: {result.get('msg', result)}")
            items = result.get("deviceListItems") or []
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise RuntimeError("device discovery returned an invalid deviceListItems list")
            devices.extend(items)
            total = result.get("total")
            if total is None:
                total = result.get("totalCount")
            if total is not None and (isinstance(total, bool) or not str(total).isdigit()):
                raise RuntimeError("device discovery returned an invalid total")
            if (total is not None and len(devices) >= int(total)) or len(items) < page_size:
                break
            page += 1
        return devices

    def station_latest(self, station_id: Any) -> JsonDict:
        result = self.post(
            self._url("station/latest"), {"stationId": station_id}, self._auth_headers()
        )
        if result.get("success") is False:
            raise RuntimeError(f"station telemetry failed: {result.get('msg', result)}")
        return result

    def tou_config(self, device_sn: str) -> JsonDict:
        result = self.post(
            self._url("config/tou"),
            {"deviceSn": device_sn},
            self._auth_headers(),
        )
        if result.get("success") is False:
            raise RuntimeError(f"TOU config read failed: {result.get('msg', result)}")
        return result

    @staticmethod
    def validate_dynamic_payload(payload: JsonDict) -> None:
        """Validate the documented minimum shape of /strategy/dynamicControl."""
        if not isinstance(payload, dict) or not payload:
            raise ValueError("dynamic-control payload must be a non-empty JSON object")
        if not payload.get("deviceSn"):
            raise ValueError("dynamic-control payload requires deviceSn")
        if not payload.get("workMode"):
            raise ValueError("dynamic-control payload requires workMode")
        slots = payload.get("timeUseSettingItems")
        if not isinstance(slots, list) or not slots:
            raise ValueError("dynamic-control payload requires timeUseSettingItems")
        for i, slot in enumerate(slots):
            if not isinstance(slot, dict):
                raise ValueError(f"timeUseSettingItems[{i}] must be an object")
            for field in ("time", "power", "soc"):
                if field not in slot:
                    raise ValueError(f"timeUseSettingItems[{i}] missing {field}")

    def dynamic_control(self, payload: JsonDict, *, execute: bool = False) -> JsonDict:
        """Preview or send Deye's documented Dynamic Control request.

        Official Deye sample code uses POST /strategy/dynamicControl. Writes remain
        opt-in so this can be safely reviewed before touching a buyer's inverter.
        """
        self.validate_dynamic_payload(payload)
        preview = {
            "path": "strategy/dynamicControl",
            "payload": payload,
            "execute": execute,
        }
        if not execute:
            return {"dry_run": True, **preview}
        result = self.post(
            self._url("strategy/dynamicControl"), payload, self._auth_headers()
        )
        return {"dry_run": False, "request": preview, "response": result}

    def order_status(self, order_id: str) -> JsonDict:
        """Read one Dynamic Control order result via GET /order/{orderId}."""
        order_id = str(order_id).strip()
        if not order_id:
            raise ValueError("order_id cannot be empty")
        return self.get(self._url(f"order/{quote(order_id, safe='')}"), self._auth_headers())

    def control(
        self,
        path: str,
        payload: JsonDict,
        *,
        execute: bool = False,
    ) -> JsonDict:
        """Validate or execute one buyer-specified Dynamic Control call.

        We do not guess write payload schemas. The paid buyer can supply the
        documented path/payload, this method shows exactly what will be sent,
        and --execute is required to make a live write.
        """
        allowed = {
            "order/sys/tou/update",
            "order/sys/solarSell/control",
            "strategy/dynamicControl",
        }
        path = path.lstrip("/")
        if path not in allowed:
            raise ValueError(f"control path is not in the reviewed allowlist: {path}")
        if not isinstance(payload, dict) or not payload:
            raise ValueError("control payload must be a non-empty JSON object")
        preview = {"path": path, "payload": payload, "execute": execute}
        if not execute:
            return {"dry_run": True, **preview}
        result = self.post(self._url(path), payload, self._auth_headers())
        return {"dry_run": False, "request": preview, "response": result}


def station_id(station: JsonDict) -> Any:
    value = station.get("id")
    return value if value is not None else station.get("stationId")


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        hidden = {"accesstoken", "appsecret", "password", "token", "authorization"}
        return {
            k: ("***" if k.lower() in hidden else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DeyeCloud EMS PoC diagnostic client")
    p.add_argument("--base-url", default=os.getenv("DEYE_BASE_URL", "https://eu1-developer.deyecloud.com/v1.0"))
    p.add_argument("--app-id", default=os.getenv("DEYE_APP_ID"))
    p.add_argument("--app-secret", default=os.getenv("DEYE_APP_SECRET"))
    p.add_argument("--login", default=os.getenv("DEYE_LOGIN"))
    p.add_argument("--password", default=os.getenv("DEYE_PASSWORD"))
    p.add_argument("--company-id", default=os.getenv("DEYE_COMPANY_ID"))
    p.add_argument("--control-path", help="Buyer-provided Dynamic Control path, e.g. order/.../update")
    p.add_argument("--payload-json", help="Buyer-provided JSON payload for --control-path")
    p.add_argument(
        "--dynamic-control-json",
        help="JSON payload for the official /strategy/dynamicControl endpoint",
    )
    p.add_argument("--poll-order-id", help="Read status for an existing Dynamic Control order ID")
    p.add_argument("--execute", action="store_true", help="Actually send the control write. Default is dry-run.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.payload_json and not args.control_path:
        print("--payload-json requires --control-path", file=sys.stderr)
        return 2
    if args.control_path and not args.payload_json:
        print("--control-path requires --payload-json", file=sys.stderr)
        return 2
    try:
        control_payload = json.loads(args.payload_json) if args.payload_json else None
        dynamic_payload = json.loads(args.dynamic_control_json) if args.dynamic_control_json else None
        if dynamic_payload is not None:
            DeyeCloudClient.validate_dynamic_payload(dynamic_payload)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"invalid control payload: {exc}", file=sys.stderr)
        return 2
    missing = [
        name
        for name, value in {
            "DEYE_APP_ID/--app-id": args.app_id,
            "DEYE_APP_SECRET/--app-secret": args.app_secret,
            "DEYE_LOGIN/--login": args.login,
            "DEYE_PASSWORD/--password": args.password,
        }.items()
        if not value
    ]
    if missing:
        print("Missing required credentials: " + ", ".join(missing), file=sys.stderr)
        return 2

    client = DeyeCloudClient(
        base_url=args.base_url,
        app_id=args.app_id,
        app_secret=args.app_secret,
        login=args.login,
        password=args.password,
        company_id=args.company_id,
    )
    if control_payload is not None:
        try:
            client.control(args.control_path, control_payload)
        except ValueError as exc:
            print(f"invalid control request: {exc}", file=sys.stderr)
            return 2
    client.authenticate()
    stations = client.stations()
    ids = [sid for s in stations if (sid := station_id(s)) is not None]
    devices = client.devices(ids)
    telemetry = [client.station_latest(sid) for sid in ids]

    report: JsonDict = {
        "auth": "ok",
        "station_count": len(stations),
        "station_ids": ids,
        "device_count": len(devices),
        "devices": devices,
        "telemetry": telemetry,
    }

    if args.control_path:
        report["control"] = client.control(
            args.control_path, control_payload, execute=args.execute
        )

    if args.dynamic_control_json:
        report["dynamic_control"] = client.dynamic_control(
            dynamic_payload, execute=args.execute
        )
        response = report["dynamic_control"].get("response") or {}
        if args.execute and response.get("orderId"):
            report["dynamic_control"]["order_id"] = response["orderId"]

    if args.poll_order_id:
        report["order_status"] = client.order_status(args.poll_order_id)

    print(json.dumps(redact(report), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
