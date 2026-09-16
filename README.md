# DeyeCloud EMS diagnostic PoC

[![CI](https://github.com/kalidatuna/deyecloud-ems-poc/actions/workflows/ci.yml/badge.svg)](https://github.com/kalidatuna/deyecloud-ems-poc/actions/workflows/ci.yml)

A Python diagnostic client for DeyeCloud station discovery, device discovery, telemetry, and opt-in control requests. This is a proof of concept, not a complete energy-management scheduler or a device-validated production integration.

## Run the offline tests

Requires Python 3.10+; uses only the standard library. No account or hardware is needed for tests.

```sh
git clone https://github.com/kalidatuna/deyecloud-ems-poc.git
cd deyecloud-ems-poc
python3 -m unittest discover -v
python3 deye_diag.py --help
```

Tests use a fake HTTP transport to check request construction, discovery, telemetry, TOU readback, control gating, and order polling. They do not establish compatibility with a real inverter or validate cloud API availability.

## Read diagnostics from your account

Set credentials in your local environment; do not commit them:

```sh
export DEYE_APP_ID='your-app-id'
export DEYE_APP_SECRET='your-app-secret'
export DEYE_LOGIN='your-username-or-email'
export DEYE_PASSWORD='your-password'
python3 deye_diag.py
```

The CLI authenticates, discovers stations and devices, and fetches station telemetry. It writes a JSON report to stdout. Known credential fields are redacted recursively, but device serial numbers, station IDs, and telemetry remain in the report; review it before sharing.

| Environment variable | Purpose |
| --- | --- |
| `DEYE_APP_ID`, `DEYE_APP_SECRET` | Application credentials; required |
| `DEYE_LOGIN`, `DEYE_PASSWORD` | Account credentials; required |
| `DEYE_COMPANY_ID` | Optional company identifier |
| `DEYE_BASE_URL` | API base URL; defaults to `https://eu1-developer.deyecloud.com/v1.0` |

Equivalent command-line options are listed by `--help`. Prefer environment variables for credentials to avoid placing them in command history. Choose the API region appropriate for your account.

## Preview a control request

```sh
python3 deye_diag.py --dynamic-control-json '{"deviceSn":"REPLACE_WITH_DEVICE_SN","workMode":"ZERO_EXPORT_TO_CT","timeUseSettingItems":[{"time":"00:00","power":1000,"soc":80}]}'
```

This illustrates the minimum shape accepted by the local validator, **not a recommended inverter configuration**. Validation checks required fields, not every API constraint or electrical operating limit. The CLI still authenticates and reads diagnostics before producing the preview; dry-run means no control write, not no network calls.

Control writes require `--execute`. Use it only with a reviewed payload for the intended device. The generic `--control-path` / `--payload-json` route accepts only the three paths allowlisted in `DeyeCloudClient.control()`.

To read a returned order ID:

```sh
python3 deye_diag.py --poll-order-id ORDER_ID
```

An accepted request or returned order ID alone does not confirm successful device operation. This command performs one status read, not an automatic polling loop.

## Python API and project scope

`DeyeCloudClient` exposes `authenticate()`, `stations()`, `devices()`, `station_latest()`, `tou_config()`, `dynamic_control()`, `control()`, and `order_status()`. TOU readback is available through the Python API; the CLI does not fetch it automatically.

A control preview can be constructed offline through `client.dynamic_control(payload)` without authenticating. Live requests require authentication and explicit `execute=True`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and [PROPOSAL.md](PROPOSAL.md) for the original pilot context. Cloud behavior, firmware-specific payloads, and a full EMS policy remain outside the offline test coverage.
