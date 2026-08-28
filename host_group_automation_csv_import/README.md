# Host Group Automation CSV Importer

This standalone script imports host groups from a CSV file into Cisco Secure Network Analytics (SNA) through the Host
Group Automation API on an SNA Manager (SMC).

## Requirements

- An SMC running version 7.6.1 or later.
- Credentials for an SMC user account with the Power Analyst or Primary Admin Web Role.
- Network connectivity to the SNA Manager.
- Python 3.13 or later.
- `pip` for installing Python packages.
- The Python `venv` module for creating a virtual environment.
- A local CA bundle that trusts the SNA Manager's identity certificate. If one is unavailable, you can disable TLS
  verification with `--disable-tls-verify`.

## Setup

Download or copy `import_csv_host_groups.py`, `requirements.txt`, and the CSV data you want to import to the system
where you will run the import script. Then create a virtual environment and install the utility's dependency:

```shell
cd <directory-containing-the-utility-files>
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -r requirements.txt
```

Before running the import, configure `requests` to trust the root CA for the SNA Manager's identity certificate:

```shell
export REQUESTS_CA_BUNDLE=<path-to-root-CA-certificate>
```

If a CA bundle is unavailable, add `--disable-tls-verify` to the command in the Usage section. This disables certificate 
validation. Make sure you are aware of the security implications of disabling certificate verification before doing so.

Provide credentials through environment variables:

```shell
export SNA_USERNAME=<username>
export SNA_PASSWORD=<password>
```

To use another credential source other than environment variables, replace the `get_credentials` function.

## CSV Format

The CSV file must have a valid header row containing the columns configured by `hostGroupNameSourceColumn` and
`ipRangesSourceColumn`. The default column names are `host_group` and `ip_ranges`; header names must match the 
configured names exactly.

Forward slashes in `host_group` values create nested groups, e.g. "Engineering/Test Environment" will create a
host group named "Test Environment" under a host group named "Engineering." 

When a row contains multiple IP ranges, enclose the comma-separated value in quotation marks, e.g. "1.2.3.4,5.6.7.8"

See [`example-data.csv`](./example-data.csv) for a sample. Its final `BadData` row is intentionally invalid so the response 
demonstrates how dropped rows are reported.

## Usage

Before running the script, edit `CONFIG` in `import_csv_host_groups.py` for the target deployment, or provide the
corresponding optional arguments when you run the script. An argument overrides its `CONFIG` value for that run; when an
argument is omitted, the value in `CONFIG` is used.

At a minimum, set `domainId` to the ID shown on the Domain Properties page on the SMC for the domain you are targeting.
Choose `parentHostGroupName` (`Inside Hosts` or `Outside Hosts`) and `hostGroupName` (the container for imported groups).
If your CSV uses different headers, set `hostGroupNameSourceColumn` and `ipRangesSourceColumn` to match them.

```shell
python3 import_csv_host_groups.py \
  --smc sna-manager.example.com \
  --file example-data.csv \
  --domain-id 301 \
  --parent-host-group-name "Inside Hosts" \
  --host-group-name "CSV Import"
```

The following `CONFIG` values can be overridden:

| Config key | CLI argument |
| --- | --- |
| `domainId` | `--domain-id <integer>` |
| `dropConflictingIps` | `--drop-conflicting-ips` or `--no-drop-conflicting-ips` |
| `parentHostGroupName` | `--parent-host-group-name "Inside Hosts"` or `"Outside Hosts"` |
| `hostGroupName` | `--host-group-name <name>` |
| `hostGroupNameSourceColumn` | `--host-group-name-source-column <column>` |
| `ipRangesSourceColumn` | `--ip-ranges-source-column <column>` |

The camelCase config-key spellings are also accepted as argument aliases, such as `--domainId` and
`--dropConflictingIps`.

Run `./import_csv_host_groups.py --help` to see all arguments.

## Results and Dropped Data

The script prints the HTTP status followed by the API response as formatted JSON. The import endpoint drops invalid data
rows and reports the reasons in its response.

When `dropConflictingIps` is enabled, `droppedConflictingIps` lists ranges removed because they conflict with
host groups under the other top-level host group. These ranges are separate from `rowsDropped`, which includes invalid CSV
rows.

## Troubleshooting

### TLS Verification Failures

Confirm that `REQUESTS_CA_BUNDLE` points to the correct root CA certificate and that the SMC address is present in
the SMC identity certificate. If verification cannot be configured, `--disable-tls-verify` disables it for the request.
Using this option will not impact the security of your SNA deployment, but will prevent this script from performing
certificate validation. Ensure you understand the security implications of doing so.

### Conflicting IPs

An HTTP 500 response can indicate that the import contains IP ranges conflicting with host groups under the other
top-level host group. Detailed error messages are available in the svc-host-group-automation.log file on the SMC.

You can set `dropConflictingIps` to `True` in `CONFIG`, or pass `--drop-conflicting-ips`, to drop any IP ranges that
conflict.

### Authentication or Authorization Failures

For authentication failures, verify `SNA_USERNAME` and `SNA_PASSWORD` and confirm that the SNA Manager permits non-SSO sign-in.
For authorization failures during import, confirm that the account has the Power Analyst or Primary Admin Web Role.

## Details About Host Group Creation

- **What will performing a CSV import with the same data and config multiple times do?**: Host group creation is
idempotent, so running it multiple times will give the same result as running it once. It will not create duplicate
host groups.
- **What happens if the hostGroupName specified in the config already exists?**: If a host group with the given hostGroupName
already exists under the given parentHostGroupName (top level host group), then child host groups will be created underneath it.
It will not be edited.
- **Will the CSV import delete existing host groups under the parent if run again with different data?**: No. If the parent
host group you specify (e.g. "CSV Import" under the top level group "Outside Hosts") already exists, the CSV import will
not delete any host groups under it. However, it will update them to remove any stale IP ranges to match the new data
provided.
