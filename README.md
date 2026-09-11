# DeyeCloud EMS diagnostic PoC

This is a small proof for a public paid fixed-price EMS request involving a Deye SUN-20K-SG05LP3-EU-SM2 and ~48 kWh battery system.

It reuses the API contract already exercised by the public `hass-deyecloud` integration:

- token authentication using App ID/App Secret plus username or email;
- `/station/list` station discovery;
- `/station/device` device discovery;
- `/station/latest` telemetry;
- `/config/tou` readback of the inverter's time-of-use program;
- official `/strategy/dynamicControl` write requests;
- `/order/{orderId}` command-result polling;
- selected bearer-authenticated `order/...` control requests.

The exact Dynamic Control endpoint is no longer guessed. Deye's own public sample repository contains four worked examples using `POST /strategy/dynamicControl`, including full charge, self-consumption, idle and feed-in-grid modes. The same public API ecosystem documents asynchronous order acknowledgement via an `orderId`, which can be checked at `GET /order/{orderId}`.

## Safety boundary

The diagnostic tool **never sends a control write by default**. A buyer-provided path and payload are printed as a dry-run. Live control requires an explicit `--execute` flag.

That is deliberate: the buyer said they already have a detailed technical specification, so this proof does not invent undocumented payload schemas or touch a real inverter without their test access.

## Tests

```bash
python3 -m unittest -v test_deye_diag.py
```

The tests use a fake HTTP transport and cover authentication payloads, discovery, telemetry, TOU readback, reviewed write-path allowlisting, Dynamic Control validation, dry-run behavior, explicit live-control gating and order-result polling.

## Live PoC flow after buyer acceptance

```bash
export DEYE_APP_ID='...'
export DEYE_APP_SECRET='...'
export DEYE_LOGIN='...'
export DEYE_PASSWORD='...'

python3 deye_diag.py

# Validate the official Dynamic Control packet without sending it:
python3 deye_diag.py \
  --dynamic-control-json '{"deviceSn":"...","workMode":"ZERO_EXPORT_TO_CT","gridChargeAction":"on","touAction":"on","touDays":["SUNDAY","MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY"],"timeUseSettingItems":[{"enableGeneration":false,"enableGridCharge":true,"power":4000,"soc":80,"time":"00:10"}]}'

# Only after the buyer approves a test device and exact payload:
python3 deye_diag.py \
  --dynamic-control-json '{"deviceSn":"...","workMode":"ZERO_EXPORT_TO_CT","gridChargeAction":"on","touAction":"on","touDays":["SUNDAY","MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY"],"timeUseSettingItems":[{"enableGeneration":false,"enableGridCharge":true,"power":4000,"soc":80,"time":"00:10"}]}' \
  --execute

# Poll the returned order ID:
python3 deye_diag.py --poll-order-id ORDER_ID
```
