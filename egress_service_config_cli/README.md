# Egress Service Configuration CLI

This standalone script remotely configures the Cisco Secure Network Analytics (SNA) Egress
Service (`svc-ndr-adapter`), which runs on a Flow Collector (FC) and exports flow data from the
FC to external destinations such as syslog, Kafka, or Splunk. Run this script from your own
workstation or a jump host with network access to the FC — it does not need to be installed or
run on the FC itself. It lets TAC engineers and customers check service health, view the enabled
flow export target, configure the syslog exporter, and reset configuration, without
hand-building `curl` commands and managing cookies and XSRF tokens.

This API was introduced in SNA 7.6.1.

## Requirements

- An FC running the Egress Service (`svc-ndr-adapter`), reachable over HTTPS from where you run
  this script.
- The FC's built-in `admin` user. Other users are not supported, even if they have the
  Master Admin web role.
- Network connectivity from the client host to the FC on HTTPS (port 443).
- Python 3.9 or later on the machine running this script (not on the FC).

## Setup

No external packages are required — the script uses only the Python standard library.
Copy the script to any machine with Python 3.9+ and run it directly:

```shell
chmod +x egress_service_configure.py
```

Provide the FC address(es) and credentials through environment variables, or pass them as
arguments on each command:

```shell
export SVC_NDR_ADAPTER_FC=<FC_IP_or_hostname>
export SVC_NDR_ADAPTER_USERNAME=admin
export SVC_NDR_ADAPTER_PASSWORD=<admin-password>
```

To target multiple FCs, comma-separate them or pass `--fc` more than once:

```shell
export SVC_NDR_ADAPTER_FC=10.0.0.1,10.0.0.2,10.0.0.3
```

To use another credential source, replace the `get_credentials` function.

Most FCs use self-signed certificates. If your client does not trust the FC certificate chain,
add the FC CA or leaf certificate to the local trust store on the workstation or jump host that
runs this script. As a fallback, pass `--disable-tls-verify` to skip TLS certificate validation
for that run only.

If you do not set `SVC_NDR_ADAPTER_USERNAME` or `SVC_NDR_ADAPTER_PASSWORD`, the script
prompts for them interactively (the password prompt does not echo input). The prompt is the
safest option: a password passed with `--password` or typed into an `export` command is kept
in shell history.

## Usage

Run `./egress_service_configure.py --help` to see all commands and options.

### Check service health

Confirm the Egress Service container is running and reachable through the FC route:

```shell
./egress_service_configure.py health-check
```

Expected output:

```text
HTTP 200
{
  "status": "ok"
}
```

### Show the currently enabled exporter

Query which exporter (csv, syslog, kafka, splunk) is active, without exposing credentials:

```shell
./egress_service_configure.py status
```

Example output when syslog is enabled:

```text
HTTP 200
{
  "enabled_exporter": "syslog"
}
```

When no exporter is configured:

```text
HTTP 200
{
  "enabled_exporter": null
}
```

### Configure the syslog exporter

Set the syslog destination, format, and enable the exporter in a single command:

```shell
./egress_service_configure.py syslog \
  --destinations 10.1.2.3:514 \
  --format csv \
  --enable
```

Expected output:

```text
HTTP 200
{
  "updated": {
    "flow_adapter": {
      "enabled_exporters": "syslog"
    },
    "syslog": {
      "destinations": "10.1.2.3:514",
      "format": "csv",
      "enabled": "true"
    }
  }
}
```

`--destinations`, `--format`, and `--enable` can be combined or used individually. At least
one option must be provided.

To stop syslog export, run:

```shell
./egress_service_configure.py syslog --disable
```

`--disable` uses the reset API: it sets `syslog.enabled` to `false` and, if syslog is the
enabled exporter, clears `enabled_exporters`. It does not change another enabled exporter and
cannot be combined with `--destinations` or `--format`.

`--format` accepts `csv` (the default on a new install) or `json`. If you omit it, the format
already configured on the FC is kept, so the examples set it explicitly to make the result
predictable. Use `--format json` if your receiver expects JSON.

Syslog is sent over UDP, one flow per message. If you list more than one destination, each
receives every flow. Only one exporter can be enabled at a time; if another exporter is
enabled, run `reset` first.

### Set an arbitrary configuration value

Use `configure` with one or more `--set section.key=value` options for values not covered
by the `syslog` convenience command:

```shell
./egress_service_configure.py configure \
  --set kafka.bootstrap_servers=broker1:9092,broker2:9092 \
  --set kafka.topic=flow-records
```

Avoid passing secrets such as `kafka.sasl_password` or `splunk.hec_token` with `--set`:
command-line arguments are kept in shell history and visible to other users in the process
list. The script masks these values in the printed response.

### Reset configuration

Reset the currently enabled exporter (auto-detected; connection settings are preserved):

```shell
./egress_service_configure.py reset
```

Example output when Kafka was the enabled exporter:

```text
HTTP 200
{
  "reset": {
    "flow_adapter": {
      "enabled_exporters": ""
    },
    "kafka": {
      "enabled": "false"
    }
  }
}
```

Reset a specific key to its service default:

```shell
./egress_service_configure.py reset --section syslog --key destinations
```

```text
HTTP 200
{
  "reset": {
    "syslog": {
      "destinations": "localhost:514"
    }
  }
}
```

### Configure multiple Flow Collectors

To apply the same configuration to several FCs at once, pass multiple `--fc` arguments or
a comma-separated list:

```shell
./egress_service_configure.py \
  --fc 10.0.0.1,10.0.0.2,10.0.0.3 \
  --disable-tls-verify \
  syslog --destinations 10.1.2.3:514 --format csv --enable
```

Or using repeated `--fc`:

```shell
./egress_service_configure.py \
  --fc 10.0.0.1 --fc 10.0.0.2 --fc 10.0.0.3 \
  --disable-tls-verify \
  health-check
```

The script authenticates and runs the command on each FC sequentially, printing results
separated by the FC address. The exit code is non-zero if any FC fails.

Example output:

```text
--- 10.0.0.1 ---
HTTP 200
{
  "status": "ok"
}

--- 10.0.0.2 ---
HTTP 200
{
  "status": "ok"
}

--- 10.0.0.3 ---
HTTP 200
{
  "status": "ok"
}
```

## Supported Configuration Values

| Section | Key | Supported values |
| --- | --- | --- |
| `syslog` | `destinations` | One or more `host:port` entries, comma-separated. Ports must be 1–65535. |
| `syslog` | `enabled` | `true` or `false` |
| `syslog` | `format` | `csv` or `json` |

The `configure` command also accepts values for the `flow_adapter`, `csv`, `kafka`,
`splunk`, `logging`, and `monitoring` sections. Refer to the Egress Service API
documentation included with your SNA release for the complete list.

## Scripting

Pass `--quiet` (`-q`) to suppress the `HTTP ...` status line on successful responses.
The JSON body is still printed to stdout, making it easy to pipe into `jq`:

```shell
ENABLED=$(./egress_service_configure.py -q status | jq -r '.enabled_exporter')
echo "Current exporter: ${ENABLED}"
```

The exit code is non-zero when the API returns an error status.

## Troubleshooting

### TLS Verification Failures

Most FCs use self-signed certificates. Pass `--disable-tls-verify` to skip validation.
This prevents the script from verifying the FC's identity, so your admin credentials could
be sent to an impostor on an untrusted network. Prefer adding the FC certificate to your
local trust store.

### 401 Unauthorized

Confirm the FC address, username, and password are correct.

### 403 Forbidden

Confirm you are signing in as the FC's built-in `admin` user. Other users are not supported,
even if they have the Master Admin web role.

### 400 Invalid configuration request

Confirm the section, key, and value are supported. Use the supported values table above
and the Egress Service API documentation included with your SNA release for reference.

If you are enabling an exporter while a different one is still enabled, the request is
rejected with this error. Run `./egress_service_configure.py reset`, then retry.

### No flow records received by syslog

1. Confirm syslog is enabled: `./egress_service_configure.py status` should show
   `"enabled_exporter": "syslog"`.
2. Confirm the destination is reachable from the FC and the configured port accepts UDP
   traffic.
3. Confirm there is active traffic flowing through the FC (the Egress Service only exports
   records when the FC is processing flows).

### Health check fails

Confirm the Egress Service container is running on the FC and the FC route
(`/svc-ndr-adapter`) is available. On the FC, run:

```shell
docker ps | grep svc-ndr-adapter
```
