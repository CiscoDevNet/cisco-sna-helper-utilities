#!/usr/bin/env python3
"""Command-line client for the Cisco Secure Network Analytics Egress Service API.

Run this script from your own workstation or a jump host; it only makes remote HTTPS calls
to the Egress Service (svc-ndr-adapter) REST API exposed on an FC (Flow Collector) and does
not need to run on the FC itself. It lets TAC engineers and customers check service health,
view the enabled exporter, configure the syslog exporter, and reset configuration without
constructing raw curl commands by hand.

No external packages are required — only Python 3.9+ (standard library).

See README.md in this directory for full usage and setup instructions.
"""

import argparse
import getpass
import http.cookiejar
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TIMEOUT_SECONDS = 30
AUTHENTICATE_PATH = "/token/v2/authenticate"
SERVICE_ROUTE = "/svc-ndr-adapter"


class ApiError(Exception):
    """Raised when the Egress Service API returns an error response."""


class ApiResponse:
    """Lightweight response wrapper matching what the command functions expect."""

    def __init__(self, status_code, body):
        # type: (int, str) -> None
        self.status_code = status_code
        self.body = body
        self.ok = 200 <= status_code < 300

    def json(self):
        # type: () -> Any
        return json.loads(self.body)


def build_ssl_context(verify):
    # type: (bool) -> ssl.SSLContext
    """Return an SSL context that either verifies certs or skips verification."""
    if verify:
        return ssl.create_default_context()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_credentials(args):
    # type: (argparse.Namespace) -> Tuple[str, str]
    """Return (username, password), preferring CLI args, then env vars, then a prompt."""
    username = args.username or os.environ.get("SVC_NDR_ADAPTER_USERNAME")
    if not username:
        username = input("FC admin username: ")

    password = args.password or os.environ.get("SVC_NDR_ADAPTER_PASSWORD")
    if not password:
        password = getpass.getpass("FC admin password: ")

    return username, password


def authenticate(cookie_jar, fc, username, password, ssl_context):
    # type: (http.cookiejar.CookieJar, str, str, str, ssl.SSLContext) -> str
    """Log in to the FC and return the XSRF token."""
    url = "https://{}{}".format(fc, AUTHENTICATE_PATH)
    data = urllib.parse.urlencode({"username": username, "password": password}).encode("utf-8")

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar),
        urllib.request.HTTPSHandler(context=ssl_context),
    )

    try:
        response = opener.open(url, data=data, timeout=DEFAULT_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        raise ApiError("Authentication failed: HTTP {}".format(exc.code))
    except urllib.error.URLError as exc:
        raise ApiError("Cannot reach FC at {}: {}".format(fc, exc.reason))

    # Extract XSRF token from cookies
    token = None
    for cookie in cookie_jar:
        if "XSRF" in cookie.name.upper() or "TOKEN" in cookie.name.upper():
            token = cookie.value
            break

    if not token:
        # Fall back to parsing Set-Cookie headers
        for header_value in response.headers.get_all("Set-Cookie") or []:
            match = re.search(r"TOKEN=([^;]*)", header_value)
            if match:
                token = match.group(1)
                break

    if not token:
        raise ApiError("Authentication succeeded but no XSRF token was returned")

    return token


def call_api(cookie_jar, fc, xsrf_token, method, path, ssl_context, json_body=None):
    # type: (http.cookiejar.CookieJar, str, str, str, str, ssl.SSLContext, Optional[Dict[str, Any]]) -> ApiResponse
    """Make an authenticated request to the Egress Service API."""
    url = "https://{}{}{}".format(fc, SERVICE_ROUTE, path)

    headers = {"X-XSRF-TOKEN": xsrf_token}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar),
        urllib.request.HTTPSHandler(context=ssl_context),
    )

    try:
        response = opener.open(req, timeout=DEFAULT_TIMEOUT_SECONDS)
        body = response.read().decode("utf-8")
        return ApiResponse(response.status, body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        return ApiResponse(exc.code, body)
    except urllib.error.URLError as exc:
        raise ApiError("Cannot reach FC at {}: {}".format(fc, exc.reason))


def print_response(response, quiet=False):
    # type: (ApiResponse, bool) -> None
    """Print the HTTP status and formatted JSON response."""
    if quiet:
        if not response.ok:
            print("HTTP {}".format(response.status_code), file=sys.stderr)
    else:
        print("HTTP {}".format(response.status_code))

    try:
        print(json.dumps(response.json(), indent=2))
    except (ValueError, KeyError):
        print(response.body)


def parse_set_option(raw):
    # type: (str) -> Tuple[str, str, str]
    """Parse a 'section.key=value' string into (section, key, value)."""
    try:
        path, value = raw.split("=", 1)
        section, key = path.split(".", 1)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "--set must use the form section.key=value, e.g. syslog.destinations=10.1.2.3:514"
        ) from None

    if not section or not key or not value:
        raise argparse.ArgumentTypeError(
            "--set must use the form section.key=value, e.g. syslog.destinations=10.1.2.3:514"
        )

    return section, key, value


def build_updates(set_options):
    # type: (List[Tuple[str, str, str]]) -> Dict[str, Dict[str, str]]
    """Group --set options into an updates dict keyed by section."""
    updates = {}  # type: Dict[str, Dict[str, str]]
    for section, key, value in set_options:
        updates.setdefault(section, {})[key] = value
    return updates


def cmd_health_check(cookie_jar, fc, xsrf_token, ssl_context, args):
    # type: (http.cookiejar.CookieJar, str, str, ssl.SSLContext, argparse.Namespace) -> int
    """Check Egress Service health."""
    response = call_api(cookie_jar, fc, xsrf_token, "GET", "/health-check", ssl_context)
    print_response(response, quiet=args.quiet)
    return 0 if response.ok else 1


def cmd_status(cookie_jar, fc, xsrf_token, ssl_context, args):
    # type: (http.cookiejar.CookieJar, str, str, ssl.SSLContext, argparse.Namespace) -> int
    """Show the currently enabled exporter."""
    response = call_api(cookie_jar, fc, xsrf_token, "GET", "/api/v1/config", ssl_context)
    print_response(response, quiet=args.quiet)
    return 0 if response.ok else 1


def cmd_configure(cookie_jar, fc, xsrf_token, ssl_context, args):
    # type: (http.cookiejar.CookieJar, str, str, ssl.SSLContext, argparse.Namespace) -> int
    """Set one or more configuration values."""
    updates = build_updates(args.set)
    response = call_api(cookie_jar, fc, xsrf_token, "PATCH", "/api/v1/config", ssl_context, json_body={"updates": updates})
    print_response(response, quiet=args.quiet)
    return 0 if response.ok else 1


def cmd_configure_syslog(cookie_jar, fc, xsrf_token, ssl_context, args):
    # type: (http.cookiejar.CookieJar, str, str, ssl.SSLContext, argparse.Namespace) -> int
    """Configure the syslog exporter."""
    syslog_updates = {}  # type: Dict[str, str]
    updates = {}  # type: Dict[str, Dict[str, str]]
    if args.destinations:
        syslog_updates["destinations"] = args.destinations
    if args.format:
        syslog_updates["format"] = args.format
    if args.enable:
        syslog_updates["enabled"] = "true"
        updates["flow_adapter"] = {"enabled_exporters": "syslog"}
    if args.disable:
        syslog_updates["enabled"] = "false"
        updates["flow_adapter"] = {"enabled_exporters": ""}

    if not syslog_updates:
        print("Nothing to do: provide --destinations, --format, --enable, or --disable", file=sys.stderr)
        return 2

    updates["syslog"] = syslog_updates
    response = call_api(
        cookie_jar, fc, xsrf_token, "PATCH", "/api/v1/config", ssl_context,
        json_body={"updates": updates},
    )
    print_response(response, quiet=args.quiet)
    return 0 if response.ok else 1


def cmd_reset(cookie_jar, fc, xsrf_token, ssl_context, args):
    # type: (http.cookiejar.CookieJar, str, str, ssl.SSLContext, argparse.Namespace) -> int
    """Reset the enabled exporter or a specific section/key."""
    body = {}  # type: Dict[str, Any]
    if args.section or args.key:
        if not (args.section and args.key):
            print("Both --section and --key are required together", file=sys.stderr)
            return 2
        body = {"section": args.section, "key": args.key}

    response = call_api(cookie_jar, fc, xsrf_token, "POST", "/api/v1/config/reset", ssl_context, json_body=body)
    print_response(response, quiet=args.quiet)
    return 0 if response.ok else 1


def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser(
        description="Configure the Cisco SNA Egress Service (svc-ndr-adapter) on one or more FCs over its REST API.",
        epilog="Environment variables: SVC_NDR_ADAPTER_FC, SVC_NDR_ADAPTER_USERNAME, SVC_NDR_ADAPTER_PASSWORD",
    )
    parser.add_argument("--fc", action="append",
                        help="FC IP or hostname. Can be repeated (--fc 10.0.0.1 --fc 10.0.0.2) "
                             "or comma-separated (--fc 10.0.0.1,10.0.0.2). "
                             "Also reads SVC_NDR_ADAPTER_FC env var.")
    parser.add_argument("--username", help="FC admin username (or set SVC_NDR_ADAPTER_USERNAME)")
    parser.add_argument("--password", help="FC admin password (or set SVC_NDR_ADAPTER_PASSWORD)")
    parser.add_argument(
        "--disable-tls-verify",
        action="store_true",
        help="Disable TLS certificate verification. Understand the security implications before using this.",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress the HTTP status line on success (still shown on errors via stderr). Useful for scripting.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    health_parser = subparsers.add_parser("health-check", help="Check Egress Service health")
    health_parser.set_defaults(func=cmd_health_check)

    status_parser = subparsers.add_parser("status", help="Show the currently enabled exporter")
    status_parser.set_defaults(func=cmd_status)

    configure_parser = subparsers.add_parser(
        "configure", help="Set one or more configuration values (e.g. syslog.destinations=10.1.2.3:514)"
    )
    configure_parser.add_argument(
        "--set",
        dest="set",
        action="append",
        required=True,
        type=parse_set_option,
        metavar="SECTION.KEY=VALUE",
        help="Configuration value to set. Can be passed multiple times.",
    )
    configure_parser.set_defaults(func=cmd_configure)

    syslog_parser = subparsers.add_parser("syslog", help="Configure the syslog exporter")
    syslog_parser.add_argument("--destinations",
                               help="Comma-separated host:port destinations, e.g. 10.1.2.3:514,10.1.2.4:514")
    syslog_parser.add_argument("--format", choices=["csv", "json"], help="Syslog record format")
    enable_group = syslog_parser.add_mutually_exclusive_group()
    enable_group.add_argument("--enable", action="store_true", help="Enable the syslog exporter")
    enable_group.add_argument("--disable", action="store_true", help="Disable the syslog exporter")
    syslog_parser.set_defaults(func=cmd_configure_syslog)

    reset_parser = subparsers.add_parser(
        "reset", help="Reset the enabled exporter (default), or a specific section/key"
    )
    reset_parser.add_argument("--section", help="Config section to reset, e.g. syslog")
    reset_parser.add_argument("--key", help="Config key to reset, e.g. destinations")
    reset_parser.set_defaults(func=cmd_reset)

    return parser


def resolve_fc_list(args):
    # type: (argparse.Namespace) -> List[str]
    """Build the list of FC targets from --fc args and the environment variable."""
    raw_values = args.fc or []
    env_value = os.environ.get("SVC_NDR_ADAPTER_FC", "")
    if env_value and not raw_values:
        raw_values = [env_value]

    fc_list = []
    for raw in raw_values:
        for entry in raw.split(","):
            entry = entry.strip()
            if entry and entry not in fc_list:
                fc_list.append(entry)
    return fc_list


def main():
    # type: () -> int
    parser = build_parser()
    args = parser.parse_args()

    fc_list = resolve_fc_list(args)
    if not fc_list:
        parser.error("--fc is required (or set SVC_NDR_ADAPTER_FC)")

    ssl_context = build_ssl_context(verify=not args.disable_tls_verify)
    username, password = get_credentials(args)

    multi = len(fc_list) > 1
    any_failed = False

    for fc in fc_list:
        if multi:
            print("--- {} ---".format(fc))

        cookie_jar = http.cookiejar.CookieJar()
        try:
            xsrf_token = authenticate(cookie_jar, fc, username, password, ssl_context)
        except ApiError as exc:
            print("Error [{}]: {}".format(fc, exc), file=sys.stderr)
            any_failed = True
            if multi:
                print()
            continue

        try:
            rc = args.func(cookie_jar, fc, xsrf_token, ssl_context, args)
            if rc != 0:
                any_failed = True
        except ApiError as exc:
            print("Error [{}]: {}".format(fc, exc), file=sys.stderr)
            any_failed = True

        if multi:
            print()

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
