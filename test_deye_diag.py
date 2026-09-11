import unittest

from deye_diag import DeyeCloudClient, login_field, sha256_password


class FakePost:
    def __init__(self):
        self.calls = []

    def __call__(self, url, payload, headers):
        self.calls.append((url, payload, headers))
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
        if "/order/" in url:
            return {"success": True, "msg": "accepted"}
        raise AssertionError(f"unexpected URL {url}")


class DeyeDiagTests(unittest.TestCase):
    def make_client(self):
        fake = FakePost()
        client = DeyeCloudClient(
            base_url="https://eu1-developer.deyecloud.com/v1.0",
            app_id="app",
            app_secret="secret",
            login="buyer@example.com",
            password="pw",
            post=fake,
        )
        return client, fake

    def test_auth_payload_matches_existing_integration_contract(self):
        client, fake = self.make_client()
        token = client.authenticate()
        self.assertEqual(token, "secret-token")
        _, payload, _ = fake.calls[0]
        self.assertEqual(payload["email"], "buyer@example.com")
        self.assertEqual(payload["password"], sha256_password("pw"))

    def test_discovery_and_telemetry(self):
        client, _ = self.make_client()
        client.authenticate()
        stations = client.stations()
        devices = client.devices([101])
        latest = client.station_latest(101)
        self.assertEqual(stations[0]["id"], 101)
        self.assertEqual(devices[0]["deviceSn"], "INV-1")
        self.assertEqual(latest["batterySOC"], 80)

    def test_control_is_dry_run_by_default(self):
        client, fake = self.make_client()
        client.authenticate()
        before = len(fake.calls)
        result = client.control(
            "order/battery/parameter/update",
            {"deviceSn": "INV-1", "key": "MAX_CHARGE_CURRENT", "value": 20},
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(fake.calls), before)

    def test_control_requires_explicit_execute(self):
        client, fake = self.make_client()
        client.authenticate()
        result = client.control(
            "order/sys/workMode/update",
            {"deviceSn": "INV-1", "workMode": "SELLING_FIRST"},
            execute=True,
        )
        self.assertFalse(result["dry_run"])
        self.assertTrue(result["response"]["success"])
        self.assertTrue(fake.calls[-1][0].endswith("/order/sys/workMode/update"))

    def test_rejects_non_order_write_path(self):
        client, _ = self.make_client()
        with self.assertRaises(ValueError):
            client.control("station/delete", {"stationId": 1})

    def test_login_field_supports_username_and_email(self):
        self.assertEqual(login_field("a@b.com"), {"email": "a@b.com"})
        self.assertEqual(login_field("alice"), {"username": "alice"})


if __name__ == "__main__":
    unittest.main()
