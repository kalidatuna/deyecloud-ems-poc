import contextlib
import io
import unittest
import urllib.error
from unittest.mock import Mock, patch

from deye_diag import DeyeCloudClient, http_get_json, http_post_json, login_field, main, sha256_password, station_id, redact


class FakeTransport:
    def __init__(self):
        self.calls = []

    def post(self, url, payload, headers):
        self.calls.append(("POST", url, payload, headers))
        if "/account/token?" in url:
            return {"success": True, "accessToken": "secret-token"}
        if url.endswith("/station/list"):
            return {"success": True, "stationList": [{"id": 101}]}
        if url.endswith("/station/device"):
            return {
                "success": True,
                "deviceListItems": [{"deviceSn": "INV-1", "deviceType": "INVERTER"}],
                "total": 1,
            }
        if url.endswith("/station/latest"):
            return {"success": True, "generationPower": 1200, "batterySOC": 80}
        if url.endswith("/config/tou"):
            return {"success": True, "timeUseSettingItems": [{"time": "00:00"}]}
        if url.endswith("/strategy/dynamicControl"):
            return {"success": True, "orderId": "ORDER-123"}
        if "/order/" in url:
            return {"success": True, "msg": "accepted"}
        raise AssertionError(f"unexpected URL {url}")

    def get(self, url, headers):
        self.calls.append(("GET", url, None, headers))
        if url.endswith("/order/ORDER-123"):
            return {"success": True, "status": "SUCCESS"}
        raise AssertionError(f"unexpected GET URL {url}")


class DeyeDiagTests(unittest.TestCase):
    @patch("deye_diag.urllib.request.urlopen")
    def test_http_error_does_not_echo_sensitive_response_body(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://example.com", 400, "Bad Request", {}, io.BytesIO(b"password=private-secret")
        )
        for call in (lambda: http_get_json("https://example.com", {}),
                     lambda: http_post_json("https://example.com", {}, {})):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400") as error:
                call()
            self.assertNotIn("private-secret", str(error.exception))

    @patch("deye_diag.urllib.request.urlopen")
    def test_http_helpers_reject_json_arrays(self, urlopen):
        urlopen.side_effect = lambda *_args, **_kwargs: io.BytesIO(b"[]")
        for call in (lambda: http_get_json("https://example.com", {}),
                     lambda: http_post_json("https://example.com", {}, {})):
            with self.assertRaisesRegex(RuntimeError, "must be an object"):
                call()

    @patch.object(DeyeCloudClient, "authenticate")
    def test_invalid_cli_control_payload_never_authenticates(self, authenticate):
        credentials = ["--app-id", "app", "--app-secret", "secret", "--login", "alice", "--password", "pw"]
        for options in (
            ["--dynamic-control-json", '{"deviceSn":"INV-1"}'],
            ["--control-path", "station/delete", "--payload-json", '{"deviceSn":"INV-1"}'],
            ["--control-path", "strategy/dynamicControl", "--payload-json", "not-json"],
        ):
            with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(credentials + options), 2)
        authenticate.assert_not_called()

    def make_client(self):
        fake = FakeTransport()
        client = DeyeCloudClient(
            base_url="https://eu1-developer.deyecloud.com/v1.0",
            app_id="app",
            app_secret="secret",
            login="buyer@example.com",
            password="pw",
            post=fake.post,
            get=fake.get,
        )
        return client, fake

    def test_credentials_cannot_be_sent_to_insecure_base_url(self):
        for url in ("http://example.com/v1.0", "https://user:pass@example.com/v1.0", "https://example.com/?token=abc", "not-a-url"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "HTTPS"):
                DeyeCloudClient(url, "app", "secret", "alice", "pw")

    def test_auth_payload_matches_existing_integration_contract(self):
        client, fake = self.make_client()
        token = client.authenticate()
        self.assertEqual(token, "secret-token")
        _, _, payload, _ = fake.calls[0]
        self.assertEqual(payload["email"], "buyer@example.com")
        self.assertEqual(payload["password"], sha256_password("pw"))

    def test_auth_failure_does_not_echo_server_message(self):
        client, _ = self.make_client()
        client.post = Mock(return_value={"success": False, "msg": "appSecret=private-secret"})
        with self.assertRaisesRegex(RuntimeError, "token request failed") as error:
            client.authenticate()
        self.assertNotIn("private-secret", str(error.exception))

    def test_url_components_are_encoded(self):
        client, fake = self.make_client()
        client.app_id = "app&other=1"
        client.authenticate()
        self.assertIn("appId=app%26other%3D1", fake.calls[0][1])
        client.get = Mock(return_value={"success": True})
        client.order_status("A/B?state=1")
        self.assertTrue(client.get.call_args.args[0].endswith("/order/A%2FB%3Fstate%3D1"))

    def test_discovery_and_telemetry(self):
        client, _ = self.make_client()
        client.authenticate()
        stations = client.stations()
        devices = client.devices([101])
        latest = client.station_latest(101)
        self.assertEqual(stations[0]["id"], 101)
        self.assertEqual(devices[0]["deviceSn"], "INV-1")
        self.assertEqual(latest["batterySOC"], 80)

    def test_invalid_station_list_is_reported_before_device_calls(self):
        client, _ = self.make_client()
        client.token = "test-token"
        for stations in ({"id": 101}, ["station-101"]):
            with self.subTest(stations=stations):
                client.post = Mock(return_value={"stationList": stations})
                with self.assertRaisesRegex(RuntimeError, "invalid stationList"):
                    client.stations()

    def test_control_is_dry_run_by_default(self):
        client, fake = self.make_client()
        client.authenticate()
        before = len(fake.calls)
        result = client.control(
            "order/sys/solarSell/control",
            {"deviceSn": "INV-1", "action": "on"},
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(fake.calls), before)

    def test_control_requires_explicit_execute(self):
        client, fake = self.make_client()
        client.authenticate()
        result = client.control(
            "order/sys/tou/update",
            {"deviceSn": "INV-1", "timeUseSettingItems": []},
            execute=True,
        )
        self.assertFalse(result["dry_run"])
        self.assertTrue(result["response"]["success"])
        self.assertTrue(fake.calls[-1][1].endswith("/order/sys/tou/update"))

    def test_failed_control_write_is_not_reported_as_success(self):
        client, _ = self.make_client()
        client.token = "test-token"
        client.post = Mock(return_value={"success": False, "msg": "device rejected"})
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            client.control("order/sys/tou/update", {"deviceSn": "INV-1"}, execute=True)
        payload = {"deviceSn": "INV-1", "workMode": "MODE", "timeUseSettingItems": [{"time": "00:00", "power": 1, "soc": 50}]}
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            client.dynamic_control(payload, execute=True)

    def test_rejects_non_order_write_path(self):
        client, _ = self.make_client()
        with self.assertRaises(ValueError):
            client.control("station/delete", {"stationId": 1})

    def test_tou_config_read(self):
        client, _ = self.make_client()
        client.authenticate()
        result = client.tou_config("INV-1")
        self.assertEqual(result["timeUseSettingItems"][0]["time"], "00:00")

    def test_dynamic_control_is_dry_run_by_default(self):
        client, fake = self.make_client()
        client.authenticate()
        before = len(fake.calls)
        payload = {
            "deviceSn": "INV-1",
            "workMode": "ZERO_EXPORT_TO_CT",
            "timeUseSettingItems": [
                {"time": "00:00", "power": 1000, "soc": 80}
            ],
        }
        result = client.dynamic_control(payload)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["path"], "strategy/dynamicControl")
        self.assertEqual(len(fake.calls), before)

    def test_dynamic_control_execute_and_poll(self):
        client, fake = self.make_client()
        client.authenticate()
        payload = {
            "deviceSn": "INV-1",
            "workMode": "ZERO_EXPORT_TO_CT",
            "gridChargeAction": "on",
            "touAction": "on",
            "touDays": ["MONDAY"],
            "timeUseSettingItems": [
                {
                    "enableGeneration": False,
                    "enableGridCharge": True,
                    "time": "00:00",
                    "power": 1000,
                    "soc": 80,
                }
            ],
        }
        sent = client.dynamic_control(payload, execute=True)
        self.assertEqual(sent["response"]["orderId"], "ORDER-123")
        self.assertTrue(fake.calls[-1][1].endswith("/strategy/dynamicControl"))
        status = client.order_status("ORDER-123")
        self.assertEqual(status["status"], "SUCCESS")
        self.assertTrue(fake.calls[-1][1].endswith("/order/ORDER-123"))

    def test_order_status_failure_is_reported(self):
        client, _ = self.make_client()
        client.token = "test-token"
        client.get = Mock(return_value={"success": False, "msg": "missing order"})
        with self.assertRaisesRegex(RuntimeError, "order status request failed"):
            client.order_status("ORDER-123")

    def test_dynamic_control_validation(self):
        client, _ = self.make_client()
        with self.assertRaisesRegex(ValueError, "deviceSn"):
            client.dynamic_control({"workMode": "ZERO_EXPORT_TO_CT", "timeUseSettingItems": [{}]})

    def test_invalid_page_size_rejected_before_transport(self):
        client, fake = self.make_client()
        for value in (0, -1, True, 1.5, "100", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "positive integer"):
                client.devices([101], page_size=value)
        self.assertEqual(fake.calls, [])

    def test_empty_station_list_does_not_call_transport(self):
        client, fake = self.make_client()
        self.assertEqual(client.devices([]), [])
        self.assertEqual(fake.calls, [])

    def test_device_pagination_with_and_without_total(self):
        for total_field in (None, "total", "totalCount"):
            with self.subTest(total_field=total_field):
                client, _ = self.make_client()
                client.token = "test-token"
                pages = [{"deviceListItems": [{"deviceSn": "A"}, {"deviceSn": "B"}]},
                         {"deviceListItems": [{"deviceSn": "C"}]}]
                if total_field:
                    for page in pages:
                        page[total_field] = 3
                client.post = Mock(side_effect=pages)
                self.assertEqual([d["deviceSn"] for d in client.devices([101], 2)], ["A", "B", "C"])
                self.assertEqual([call.args[1]["page"] for call in client.post.call_args_list], [1, 2])

    def test_pagination_stops_on_exact_total(self):
        client, _ = self.make_client()
        client.token = "test-token"
        client.post = Mock(return_value={"deviceListItems": [{"deviceSn": "A"}], "total": 1})
        self.assertEqual(len(client.devices([101], 1)), 1)
        client.post.assert_called_once()

    def test_device_pagination_stops_on_repeated_page(self):
        client, _ = self.make_client()
        client.token = "test-token"
        client.post = Mock(return_value={"deviceListItems": [{"deviceSn": "A"}]})
        with self.assertRaisesRegex(RuntimeError, "repeated a page"):
            client.devices([101], 1)
        self.assertEqual(client.post.call_count, 2)

    def test_invalid_device_pages_are_reported(self):
        for page in ({"deviceListItems": {"deviceSn": "A"}},
                     {"deviceListItems": ["A"]},
                     {"deviceListItems": [{"deviceSn": "A"}], "total": "unknown"}):
            with self.subTest(page=page):
                client, _ = self.make_client()
                client.token = "test-token"
                client.post = Mock(return_value=page)
                with self.assertRaisesRegex(RuntimeError, "invalid"):
                    client.devices([101], 1)

    def test_station_id_preserves_zero_and_falls_back_for_none(self):
        self.assertEqual(station_id({"id": 0, "stationId": 101}), 0)
        self.assertEqual(station_id({"id": None, "stationId": 101}), 101)
        self.assertEqual(station_id({"stationId": 101}), 101)
        self.assertIsNone(station_id({}))

    def test_redaction_is_recursive_and_does_not_mutate_report(self):
        report = {"nested": [{"AccessToken": "secret", "deviceSn": "test"}], "password": "pw"}
        self.assertEqual(redact(report), {"nested": [{"AccessToken": "***", "deviceSn": "test"}], "password": "***"})
        self.assertEqual(report["nested"][0]["AccessToken"], "secret")

    def test_login_field_supports_username_and_email(self):
        self.assertEqual(login_field("a@b.com"), {"email": "a@b.com"})
        self.assertEqual(login_field("alice"), {"username": "alice"})


if __name__ == "__main__":
    unittest.main()
