# DeyeCloud EMS diagnostic PoC

This is a small proof for a public paid fixed-price EMS request involving a Deye SUN-20K-SG05LP3-EU-SM2 and ~48 kWh battery system.

It reuses the API contract already exercised by the public `hass-deyecloud` integration:

- token authentication using App ID/App Secret plus username or email;
- `/station/list` station discovery;
- `/station/device` device discovery;
- `/station/latest` telemetry;
- bearer-authenticated `order/...` control requests.

The existing integration already contains a working write endpoint at `order/sys/solarSell/control`. Public discussion in the same project also shows users operating Dynamic Control endpoints such as `order/battery/parameter/update`, `order/sys/power/update`, and `order/sys/workMode/update`.

## Safety boundary

The diagnostic tool **never sends a control write by default**. A buyer-provided path and payload are printed as a dry-run. Live control requires an explicit `--execute` flag.

That is deliberate: the buyer said they already have a detailed technical specification, so this proof does not invent undocumented payload schemas or touch a real inverter without their test access.

## Tests

```bash
python3 -m unittest -v test_deye_diag.py
```

The tests use a fake HTTP transport and cover authentication payloads, discovery, telemetry, dry-run control, explicit live-control gating, and invalid write-path rejection.

## Live PoC flow after buyer acceptance

```bash
export DEYE_APP_ID='...'
export DEYE_APP_SECRET='...'
export DEYE_LOGIN='...'
export DEYE_PASSWORD='...'

python3 deye_diag.py

# Validate the exact write packet without sending it:
python3 deye_diag.py \
  --control-path order/sys/workMode/update \
  --payload-json '{"deviceSn":"...","workMode":"SELLING_FIRST"}'

# Only after the buyer approves a test device and exact payload:
python3 deye_diag.py \
  --control-path order/sys/workMode/update \
  --payload-json '{"deviceSn":"...","workMode":"SELLING_FIRST"}' \
  --execute
```
