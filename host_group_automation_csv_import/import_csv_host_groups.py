#!/usr/bin/env python3
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

"""Import host groups from a CSV file into Cisco Secure Network Analytics."""

import argparse
import json
import os
import sys
from pathlib import Path

import requests


class TopLevelHostGroup:
    """Supported values for the top-level parent host group."""
    INSIDE_HOSTS = "Inside Hosts"
    OUTSIDE_HOSTS = "Outside Hosts"


CONFIG = {
    # The ID of the domain to import host groups to. The default is intentionally invalid. You can find the ID for your
    # domain on the Domain Properties page.
    "domainId": -1,

    # The name of the parent host group to create. All host groups from the CSV data will be created under this host group.
    # If a host group with this name already exists under the parentHostGroupName you select, we will create host groups
    # under that existing host group.
    "hostGroupName": "CSV Import",

    # The top level host group, either "Inside Hosts" or "Outside Hosts", that the host groups will be created under.
    "parentHostGroupName": TopLevelHostGroup.INSIDE_HOSTS,

    # Values for the Advanced Options of created host groups. See the Host Group Management page for details.
    "hostBaselines": False,  # Enable baselining for hosts in this group
    "suppressExcludedServices": False,  # Disable security events using excluded services
    "inverseSuppression": False,  # Disable flood alarms and security events when a host in this group is the target
    "hostTrap": False,  # Trap hosts that scan unused addresses in this group

    # If enabled, Host Group Automation will filter out any IPs which would cause conflicts with host groups under the
    # other top level host group before creating host groups. If disabled, host group creation will fail with an HTTP 500
    # if any IPs conflict.
    "dropConflictingIps": False,

    # The CSV column to pull the host group name from. Forward slashes can be used to nest host groups. For example,
    # "Engineering/Test Environment" would create a host group named "Test Environment" under the "Engineering" parent.
    "hostGroupNameSourceColumn": "host_group",

    # The CSV column to pull the host group IP ranges from. Multiple IP ranges can be included, in which case they
    # should be comma-separated and enclosed in quotes, for example: "10.10.1.0/24,10.10.2.10"
    "ipRangesSourceColumn": "ip_ranges",

    # The file type being imported. As of 7.6.1, only CSV is supported.
    "fileType": "CSV"
}
"""The import config to send with the request to SNA. Modify as needed."""


class AuthenticationError(Exception):
    """Raised when authentication to the SMC fails."""


class MissingCredentialsError(Exception):
    """Raised when required SNA credentials are unavailable."""


def get_command_line_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Import host groups from a CSV file into an SNA SMC.")
    parser.add_argument(
        "--smc",
        required=True,
        help="IP address or hostname of the SMC",
    )
    parser.add_argument(
        "--file",
        required=True,
        type=Path,
        help="Path to the CSV file to import",
    )
    parser.add_argument(
        "--domain-id",
        "--domainId",
        dest="domain_id",
        type=int,
        help="ID of the SNA domain to import host groups into",
    )
    parser.add_argument(
        "--parent-host-group-name",
        "--parentHostGroupName",
        dest="parent_host_group_name",
        choices=(
            TopLevelHostGroup.INSIDE_HOSTS,
            TopLevelHostGroup.OUTSIDE_HOSTS,
        ),
        help="Top-level host group under which the import parent will be created",
    )
    parser.add_argument(
        "--host-group-name",
        "--hostGroupName",
        dest="host_group_name",
        help="Name of the parent that will contain the imported host groups",
    )
    parser.add_argument(
        "--host-group-name-source-column",
        "--hostGroupNameSourceColumn",
        dest="host_group_name_source_column",
        help="CSV column containing host group names",
    )
    parser.add_argument(
        "--ip-ranges-source-column",
        "--ipRangesSourceColumn",
        dest="ip_ranges_source_column",
        help="CSV column containing host group IP ranges",
    )
    conflicting_ips_group = parser.add_mutually_exclusive_group()
    conflicting_ips_group.add_argument(
        "--drop-conflicting-ips",
        "--dropConflictingIps",
        dest="drop_conflicting_ips",
        action="store_true",
        default=None,
        help=(
            "Drop IP ranges that conflict with host groups under the other "
            "top-level host group"
        ),
    )
    conflicting_ips_group.add_argument(
        "--no-drop-conflicting-ips",
        "--no-dropConflictingIps",
        dest="drop_conflicting_ips",
        action="store_false",
        default=None,
        help="Keep conflicting IP ranges, causing the import to fail on conflicts",
    )
    parser.add_argument(
        "--disable-tls-verify",
        dest="verify_tls",
        action="store_false",
        help="Disable TLS certificate verification (not recommended)",
    )
    return parser.parse_args()


def get_credentials() -> tuple[str, str]:
    """Retrieve SNA credentials from environment variables.
    IMPLEMENT ALTERNATE CREDENTIAL RETRIEVAL HERE IF NEEDED."""
    username = os.getenv("SNA_USERNAME")
    password = os.getenv("SNA_PASSWORD")
    if not username:
        raise MissingCredentialsError("Set SNA_USERNAME before running.")
    if not password:
        raise MissingCredentialsError("Set SNA_PASSWORD before running.")
    return username, password


def build_import_config(args: argparse.Namespace) -> dict[str, object]:
    """Copy the import config and apply command-line overrides."""
    config = CONFIG.copy()
    overrides = {
        "domainId": args.domain_id,
        "dropConflictingIps": args.drop_conflicting_ips,
        "parentHostGroupName": args.parent_host_group_name,
        "hostGroupName": args.host_group_name,
        "hostGroupNameSourceColumn": args.host_group_name_source_column,
        "ipRangesSourceColumn": args.ip_ranges_source_column,
    }
    config.update(
        {
            config_key: config_value
            for config_key, config_value in overrides.items()
            if config_value is not None
        }
    )
    return config


class SnaClient:
    """Client for authenticating to SNA and importing host groups."""
    def __init__(
        self,
        manager_address: str,
        username: str,
        password: str,
        verify_tls: bool = True,
    ) -> None:
        address = manager_address.strip()
        if ":" in address and not address.startswith("["):
            address = f"[{address}]"
        self.manager_address = address
        self._username = username
        self._password = password
        self._verify_tls = verify_tls
        self._session = requests.Session()
        self._xsrf_token: str | None = None

    def authenticate(self) -> None:
        """Authenticate to the SMC."""
        auth_url = f"https://{self.manager_address}/token/v2/authenticate"
        data = {"username": self._username, "password": self._password}
        response = self._session.post(
            auth_url,
            data=data,
            verify=self._verify_tls,
        )
        if response.status_code != 200:
            raise AuthenticationError
        self._xsrf_token = response.cookies.get("XSRF-TOKEN")

    def import_host_groups_csv(
        self,
        csv_path: Path,
        config: dict[str, object],
    ) -> requests.Response:
        """Submit a CSV file to the Host Group Automation import endpoint."""
        if not self._xsrf_token:
            raise AuthenticationError("Authenticate before importing host groups.")
        headers = {"X-XSRF-TOKEN": self._xsrf_token}
        url = f"https://{self.manager_address}/host-group-automation/import"
        with csv_path.open("rb") as csv_file:
            return self._session.post(
                url,
                data={"config": json.dumps(config)},
                files={"file": ("hga-import.csv", csv_file, "text/csv")},
                headers=headers,
                verify=self._verify_tls,
            )


def print_response(response: requests.Response) -> None:
    """Print the HTTP status and response body."""
    print(f"HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except requests.exceptions.JSONDecodeError:
        print(response.text)


def main() -> int:
    """Run the host group import."""
    args = get_command_line_args()
    if not args.file.is_file():
        print(f'CSV file "{args.file}" does not exist.', file=sys.stderr)
        return 1
    try:
        username, password = get_credentials()
        client = SnaClient(
            args.smc,
            username,
            password,
            args.verify_tls,
        )

        print("Authenticating to SMC ...")
        client.authenticate()
        print("Authentication successful.")

        print("Importing host groups...")
        response = client.import_host_groups_csv(
            args.file,
            build_import_config(args),
        )
    except MissingCredentialsError as error:
        print(error, file=sys.stderr)
        return 1
    except requests.exceptions.SSLError:
        print("TLS verification failed. Configure REQUESTS_CA_BUNDLE or, if necessary, "
              "use --disable-tls-verify.", file=sys.stderr)
        return 1
    except AuthenticationError:
        print("Authentication failed. Check your username and password.", file=sys.stderr)
        return 1
    except requests.exceptions.RequestException as error:
        print(f"Request failed: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Unable to read the CSV file: {error}", file=sys.stderr)
        return 1
    print_response(response)
    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main())
