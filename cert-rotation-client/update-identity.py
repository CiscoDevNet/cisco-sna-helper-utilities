#!/usr/bin/env python3
"""
This script is used to update appliance identity certificates for Secure Network Analytics (7.5.x) appliances managed
by a single (SNA) Manager appliance.

Note that these operations induce downtime in SNA.

See comprehensive details about this script and its impacts and limitations in the corresponding README.md file.
"""

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from time import sleep
from typing import Optional, Tuple

import requests


PATH_CM_APPLIANCES = '/cm/inventory/appliances'
PATH_CM_INVENTORY = '/cm/inventory/appliances'
PATH_CM_APPLIANCES_STATUS = '/cm/monitor/appliances/status'
PATH_CM_APPLIANCE_STATUS = '/cm/config/appliance/{}/status'
PATH_CM_NONCSR = '/cm/config/appliance/{}/certificate/non-csr'
PATH_CM_CONFIG = '/cm/config/appliance/{}/config'
PATH_CM_DATASTORE = '/cm/monitor/datastore'
PATH_CM_DATASTORE_LOCK = '/cm/monitor/datastore/lock'


class InvalidFqdnError(Exception):
    """Thrown when cert rotation is requested for an appliance using an unknown/invalid FQDN"""


class ApplianceStatusError(Exception):
    """Thrown when cert rotation is requested for an appliance that is not in the "up" state"""


class DataStoreStateError(Exception):
    """
    Thrown when DataStore is not in a required state (e.g. actions are requested but disallowed or is "up" without
    using --ack-datastore)
    """


class FailoverStateException(Exception):
    """Thrown when attempting to manage appliances via a secondary Manager appliance"""


class AuthenticationError(Exception):
    """Thrown when authentication to SNA fails"""


def get_command_line_args() ->  argparse.Namespace:
    """
    Gets command line args
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-m', '--manager-address', required=True, type=str,
                        help='Address (ip/hostname) of the primary Manager appliance')
    parser.add_argument('-f', '--pkcs-file', required=not _ro_arg_used(sys.argv), type=str,
                        help='Path to the PKCS12 file')
    parser.add_argument('-p', '--pkcs12-password', required=not _ro_arg_used(sys.argv), type=str,
                        help='Password for the PKCS12 bundle')
    parser.add_argument('--fqdns', required=True, nargs='+', type=str,
                        help='A space-separated list of FQDNs of appliances on which to install the new certificates ' \
                             'and/or to monitor for completion of certificate rotation (using -ro script argument). ' \
                             'Use "all" as a shortcut to update all appliances. Note that appliance FQDNs must match ' \
                             'the appliance FQDNs shown in Central Management.')
    parser.add_argument('--friendly-name', required=False, default=_generate_friendly_name(), type=str,
                        help='Friendly name to show in Central Management for the identity certificate')
    parser.add_argument('--shutdown-datastore', action='store_true', default=False,
                        help='If DataStore is "up", shut it down before installing new certificates (default: False)')
    parser.add_argument('--start-datastore', action='store_true', default=False,
                        help='Start DataStore after certificate rotation (default: False)')
    parser.add_argument('--ack-datastore', action='store_true', default=False,
                        help='Provide this argument to acknowledge risks of performing certificate rotation without ' \
                             'shutting down the Data Store, e.g. to proceed without shutting down the Data Store (default: False)')
    parser.add_argument('-r', '--report', action='store_true', default=False,
                        help='Monitor and report on completion of certificate rotation (default: False)')
    parser.add_argument('-ro', '--report-only', action='store_true', default=False,
                        help='Only report on completion of certificate rotation; do not perform certificate rotation (default: False)')
    parser.add_argument('-t', '--report-timeout', required=False, default=1800, type=int,
                        help='Timeout (seconds) for monitoring completion of certificate rotation (default: 1800)')
    parser.add_argument('-d', '--debug', action='store_true', default=False, help='Enable debug logging (default: False)')
    return parser.parse_args()


def _get_credentials() ->  Tuple[str, str]:
    """
    Retrieves username/password credentials from the environment.
    IMPLEMENT ALTERNATIVE CREDENTIAL RETRIEVAL CODE HERE IF NEEDED.
    """
    username = os.getenv('USERNAME')
    password = os.getenv('PASSWORD')
    return username, password


def _is_valid_friendly_name(friendly_name: str) -> bool:
    """Indicates whether the provided name matches SNA's character restrictions"""
    pattern = r'^[a-zA-Z0-9\-_\.]+$'
    return bool(re.match(pattern, friendly_name))


def _generate_friendly_name() -> str:
    """Generates a friendly_name indicative of being auto-generated by a particular script execution"""
    return f'auto_{datetime.now().strftime("%m-%d-%Y_%H.%M.%S")}'


def _ro_arg_used(args: list) -> bool:
    """Indicates if the --report-only or -ro argument was used in args"""
    arg_string = ' '.join(args)
    return '-ro' in arg_string or '--report-only' in arg_string


class ApiClient:
    """
    Client of an SNA Manager
    """

    def __init__(self, manager_address: str, username: str, password: str):
        self.manager_address = manager_address
        self._username = username
        self._password = password
        self._cookie_jar = None
        self._xsrf_token = None

    def authenticate(self) -> None:
        """
        Authenticate to the Manager (get stealthwatch.jwt cookie and XSRF token)
        """
        auth_url = f'https://{self.manager_address}/token/v2/authenticate'
        data = {'username': self._username, 'password': self._password}
        response = requests.post(auth_url, data=data)
        if not response.status_code == 200:
            raise AuthenticationError
        self._cookie_jar = response.cookies
        self._xsrf_token = self._cookie_jar['XSRF-TOKEN']

    def refresh_token(self) -> None:
        """Refreshes the SNA JWT (expires every 20 min)"""
        response = requests.post(f'https://{self.manager_address}/token/v2', cookies=self._cookie_jar,
                                 headers={'X-XSRF-TOKEN': self._xsrf_token})
        response.raise_for_status()
        self._cookie_jar = response.cookies
        self._xsrf_token = self._cookie_jar['XSRF-TOKEN']

    def fqdn(self) -> str:
        """
        Retrieves the FQDN of this Manager appliance, as known to the appliance/SNA.
        """
        response = requests.get(f'https://{self.manager_address}/fqdn', cookies=self._cookie_jar)
        response.raise_for_status()
        return response.text

    def _get_cm_url(self, url: str) ->  requests.Response:
        """Performs a GET request to the specified Central Management URL."""
        response = requests.get(f'https://{self.manager_address}{url}', cookies=self._cookie_jar)
        if response.status_code == 307:
            raise FailoverStateException
        response.raise_for_status()
        return response

    def _put_cm_url(self, url, **requests_kwargs: dict) -> requests.Response:
        """Performs a PUT request to the specified Central Management URL."""
        headers={'X-XSRF-TOKEN': self._xsrf_token}
        if 'headers' in requests_kwargs:
            headers.update(requests_kwargs['headers'])
            del requests_kwargs['headers']
        response = requests.put(f'https://{self.manager_address}{url}', cookies=self._cookie_jar, headers=headers,
                                **requests_kwargs)
        if response.status_code == 307:
            raise FailoverStateException
        response.raise_for_status()
        return response

    def cm_inventory(self) -> dict:
        """Returns the appliance inventory from Central Management."""
        return self._get_cm_url(PATH_CM_APPLIANCES).json()

    def appliances_status(self) -> dict:
        """Returns the appliances statuses from Central Management."""
        return self._get_cm_url(PATH_CM_APPLIANCES_STATUS).json()

    def appliance_status(self, appliance_id) -> dict:
        """Returns the status details of a specific appliance from Central Management."""
        return self._get_cm_url(PATH_CM_APPLIANCE_STATUS.format(appliance_id)).json()

    def datastore_status(self) -> dict:
        """Returns the status of the DataStore from Central Management."""
        return self._get_cm_url(PATH_CM_DATASTORE).json()

    def _datastore_lock(self) -> Optional[bool]:
        """Indicates if the DataStore is in a locked state"""
        response = self._get_cm_url(PATH_CM_DATASTORE_LOCK)
        match response.status_code:
            case 200:
                return True
            case 204:
                return False
            case _:
                logging.warning('Datastore lock is in an unknown state.')
                return None

    def shutdown_datastore(self) -> None:
        """Triggers shutdown of the DataStore"""
        self._datastore_action('stop')

    def start_datastore(self) -> None:
        """Triggers startup of the DataStore"""
        self._datastore_action('start')

    def _datastore_action(self, action: str) -> None:
        """Perform a specified action on the DataStore"""
        self._put_cm_url(PATH_CM_DATASTORE, json={'action': action})

    def wait_datastore_status(self, desired_status: str = 'down', timer: int = 1800, delay: int = 5) -> None:
        """Poll the DataStore for the desired status or until the timer expires"""
        while timer >= 0:
            status = self.datastore_status()
            if status.get('status') == desired_status:
                return
            sleep(delay)
            timer -= delay
        status = self.datastore_status()
        if not status.get('status') == desired_status:
            raise DataStoreStateError('Timeout elapsed waiting for DataStore to shutdown to complete.')

    def _wait_datastore_action_ready(self, timer: int = 1800, delay: int = 5) -> None:
        """
        Poll Central Management until it allows actions to be performed against Data Node appliances or until the timer
        expires
        """
        while timer >= 0:
            status = self.datastore_status()
            if status.get('allowDataStoreApplianceActions'):
                return
            sleep(delay)
            timer -= delay
        status = self.datastore_status()
        if not status.get('allowDataStoreApplianceActions'):
            raise DataStoreStateError('Timeout elapsed waiting for DataStore actions to be allowed.')

    def _send_non_csr_cert(self, appliance_id: str, friendly_name: str, pkcs12_bytes: bytes, password: str) -> dict:
        """
        Send a certificate to Central Manager using SNA's "non-csr" routine.
        This is like "staging" but not yet "applying" certificate installation.
        """
        multipart_form_data = {
            'friendlyName': (None, friendly_name),
            'bundlePassword': (None, password),
            'confirmPassword': (None, password),
            'targetCertificateFile': ('staged.p12', pkcs12_bytes, 'application/x-pkcs12'),

        }
        return self._put_cm_url(PATH_CM_NONCSR.format(appliance_id), files=multipart_form_data).json()

    def cm_config(self, appliance_id: str) -> Tuple[str, dict]:
        """
        Retrieve Central Management configuration data for the specified appliance
        """
        response = self._get_cm_url(PATH_CM_CONFIG.format(appliance_id))
        return response.headers.get('ETag', ''), response.json()

    def _apply_cert_update(self, appliance_id: str, cert_config: dict) -> None:
        """
        "Apply" the certificate configuration (update) for the specified appliance
        """
        e_tag, config_data = self.cm_config(appliance_id)
        config_data['configurableElements']['tlsApplianceIdentity'] = cert_config
        resp = self._put_cm_url(PATH_CM_CONFIG.format(appliance_id), headers={'If-Match': e_tag}, json=config_data)

    def update_identity(self, appliance_id: str, pkcs12_bytes: bytes, pkcs12_password: str, friendly_name: str,
                         is_dnode: bool = False) -> None:
        """
        Install the pkcs12 bundle as the appliance identity bundle for the specified appliance.
        """
        logging.debug(f'Starting rotation for appliance: {appliance_id}...')
        if is_dnode:
            self._wait_for_datastore_lock_release()
            self._wait_datastore_action_ready()
        new_tls_identity_config = self._send_non_csr_cert(appliance_id, friendly_name, pkcs12_bytes, password=pkcs12_password)
        self._apply_cert_update(appliance_id=appliance_id, cert_config=new_tls_identity_config)
        logging.debug(f'Done sending requests for appliance: {appliance_id}.')


    def _wait_for_datastore_lock_release(self, timer: int = 1800, delay: int = 5) -> None:
        """
        Poll for any locks on the Data Store to be released
        """
        logging.debug('Waiting for release of any locks on DataStore...')
        while timer >= 0:
            if not self._datastore_lock():
                return
            sleep(delay)
            timer -= delay
        if self._datastore_lock():
            logging.warning('Timer elapsed while waiting for Central Management to release DataStore lock. '
                    'Proceeding (best effort) but may experience failure (HTTP 409).')



def check_completion(api_client: ApiClient, appliance_fqdns: Optional[list[str]], friendly_name: str) \
        -> Tuple[bool, list, list]:
    """
    Measures completion and successfulness of certificate rotation activities by:
    1. checking the status of appliances in the Central Manager inventory
    2. checking all specified appliances for configuration of an identity certificate using the specified friendly_name

    Note that no inspection of certificates actually presented by SNA appliances is performed (as these details are
    currently obscure to this script, are somewhat redundant to #2, & can be easily automated without knowledge of SNA.)
    """
    api_client.authenticate()
    appliances_statuses = api_client.appliances_status()
    status_by_fqdn = {appl['fqdn']: appl for appl in appliances_statuses}
    monitored_fqdns = appliance_fqdns or status_by_fqdn.keys()  # handle "all" case where appliance_fqdns is None
    successes = []
    failures = []
    for fqdn in monitored_fqdns:
        status = status_by_fqdn.get(fqdn)
        if not status:
            raise InvalidFqdnError(f'"{fqdn}" is not an appliance FQDN in the Central Manager inventory.')
        if not status.get('configurationChannelStatus') == 'up':
            return False, successes, failures
        appliance_id = status.get('id')
        state = api_client.appliance_status(appliance_id).get('configState')
        match state:
            case 'UP_TO_DATE':
                pass
            case 'APPLY_CONFIG_FAILED':
                failures.append(fqdn)
            case _:
                return False, successes, failures  # note that these lists are partial but may still be useful
        _, appl_config = api_client.cm_config(appliance_id)
        active_friendly_name = appl_config.get('configurableElements', {}).get('tlsApplianceIdentity', {}).get('friendlyName', {})
        if not active_friendly_name:
            logging.warning(f'Error finding the active friendly name for appliance with id {appliance_id}.'
                            f'This is unexpected and may cause inaccurate assessment of cert rotation task completion.')
        if  active_friendly_name == friendly_name:
            successes.append(fqdn)
        else:
            failures.append(fqdn)
    return True, successes, failures


def monitor_completion(api_client: ApiClient, appliance_fqdns: Optional[list[str]], friendly_name: str,
                       timer: int = 1800, delay: int = 20) -> Optional[bool]:
    """
    Polls the SNA Manager for completion of certificate rotation activities or until the specified timeout is reached,
    returning a boolean indicating whether the rotation was successful or not or None if the timeout was reached.

    Note that the timeout isn't a precise "wall-clock" timeout (moreso an approximation) since actions within the
    polling loop aren't necessarily instantaneous and the timeout functions moreso as a loop counter.
    """
    logging.info(f'Monitoring completion of cert rotation for {timer} seconds...')
    while True:
        try:
            complete, successes, failures =  check_completion(api_client, appliance_fqdns, friendly_name)
            if complete:
                logging.info(f'Certificate rotation actions appear complete.\n'
                             f'Successes: {', '.join(successes) or "None"}\n'
                             f'Failures: {', '.join(failures) or "None"}')
                return not failures
            logging.debug('Certificate rotation actions still appear to be in progress.')
        except (AuthenticationError, requests.exceptions.HTTPError, requests.exceptions.ConnectTimeout,
                requests.exceptions.ConnectionError):
            # these are expected while Manager reboots
            pass
        if timer >= 0:
            sleep(delay)
            timer -= delay
        else:
            logging.warning('Time elapsed while monitoring for completion of certificate rotation.')
            return None


def _process_fqdns(api_client: ApiClient, appliance_fqdns: Optional[list[str]] = None) -> Tuple[list, list, Optional[str]]:
    """
    Validate the provided FQDNs (or if appliance_fqdns is None, collect the list of all FQDNs from Central Management),
    then characterize each appliance (fqdn) into one of 3 categories (returned as a Tuple) that need distinct handling:
    1. all (specified) appliances that aren't Data Node appliances or the Primary Manager (SMC)
    2. all (specified) appliances that are Data Node appliances
    3. the primary SMC (if specified)

    FQDN validation entails ensuring that all specified FQDNs correlate to appliances present in the Central Management
    inventory and that all appliances are "up" and ready for configuration changes.
    """
    # Collect and transform cluster info
    primary_smc_fqdn = api_client.fqdn()
    inventory = api_client.cm_inventory()
    inventory_by_fqdn = {appl['fqdn']: appl for appl in inventory}
    appliances_statuses = api_client.appliances_status()
    status_by_fqdn = {appl['fqdn']: appl.get('configurationChannelStatus') for appl in appliances_statuses}
    appliance_fqdns = appliance_fqdns or list(inventory_by_fqdn.keys())  # if no list provided, do all appliances

    # iterate through provided FQDNs to validate and characterize fqdns
    appliance_ids = []
    dnode_ids = []
    smc_id = None
    for fqdn in appliance_fqdns:
        # perform fqdn and appliance status validations
        status = status_by_fqdn.get(fqdn)
        if not status:
            raise InvalidFqdnError(f'"{fqdn}" is not an appliance FQDN in the Central Manager inventory.')
        if not status == 'up':
            raise ApplianceStatusError(f'Appliance "{fqdn}" is not in "up" status.')
        appliance_id = inventory_by_fqdn.get(fqdn).get('id')
        if not appliance_id:
            raise ApplianceStatusError(f'Cannot find "id" attribute for appliance "{fqdn}".')
        if not api_client.appliance_status(appliance_id).get('configState') == 'UP_TO_DATE':
            raise ApplianceStatusError(f'Appliance "{fqdn}" is not ready for configuration changes.')

        # characterize the appliance by type
        if inventory_by_fqdn[fqdn].get('applianceType') == 'DB_CLUSTER_NODE':
            dnode_ids.append(appliance_id)
        elif not fqdn == primary_smc_fqdn:
            appliance_ids.append(appliance_id)
        else:
            smc_id = appliance_id
        
    return appliance_ids, dnode_ids, smc_id

def rotate_certs(api_client: ApiClient, pkcs12_bytes: bytes, pkcs12_password: str, friendly_name: str,
                 appliance_fqdns: Optional[list[str]] = None, shutdown_ds: bool = False, ack_ds: bool = False) -> None:
    """
    Install the pkcs12 bundle to appliances specified by appliance_fqdns.
    The Data Store must already be "down" or shutdown_ds or ack_ds must be True.
    """
    appliance_ids, dnode_ids, smc_id = _process_fqdns(api_client, appliance_fqdns)
    
    # Check/manage Data Store state if rotating certs on Data Node appliances
    if dnode_ids and not api_client.datastore_status().get('status') == 'down':
        if shutdown_ds:
            logging.info('Shutting down datastore...')
            api_client.shutdown_datastore()
            api_client.wait_datastore_status('down')
        elif not ack_ds:
            raise DataStoreStateError('Datastore is "up" and user has not allowed this via --ack-datastore argument.')
        elif not api_client.datastore_status().get('allowDataStoreApplianceActions'):
            raise DataStoreStateError('Datastore actions are not allowed at this time.')

    num_appliances = len(dnode_ids) + len(appliance_ids) + (smc_id and 1 or 0)
    logging.info(f'Starting certificate rotation for {num_appliances} appliances...')

    # trigger cert update for Data Node appliances
    for appliance_id in dnode_ids:
        api_client.update_identity(appliance_id, pkcs12_bytes, pkcs12_password, friendly_name, is_dnode=True)
        api_client.refresh_token()  # renew token since each dnode rotation may spend substantial token lifetime

    # trigger cert update for appliances that aren't Data Nodes or the primary SMC in the list
    for appliance_id in appliance_ids:
        api_client.update_identity(appliance_id, pkcs12_bytes, pkcs12_password, friendly_name)

    # Update the primary Manager (SMC) last so all certificate rotation api requests can be submitted before the
    # Manager reboots
    if smc_id:
        api_client.update_identity(smc_id, pkcs12_bytes, pkcs12_password, friendly_name)
        



if __name__ == '__main__':
    # process common cli args
    ARGS = get_command_line_args()
    loglevel = logging.DEBUG if ARGS.debug else logging.INFO
    logging.basicConfig(stream=sys.stdout, level=loglevel,
                        format='%(asctime)s %(levelname)s: %(message)s',  datefmt='%Y-%m-%d %H:%M:%S')
    if not _is_valid_friendly_name(ARGS.friendly_name):
        logging.error(f'"{ARGS.friendly_name}" is not a valid friendly name (can contain only alphanumerics, underscores, hyphens, and periods). Exiting.')
        sys.exit(1)
    logging.info(f'Using "{ARGS.friendly_name}" as the friendly name for identity certificates.')
    fqdns = None if ARGS.fqdns == ['all'] else ARGS.fqdns

    # setup api client
    username, password = _get_credentials()
    client = ApiClient(ARGS.manager_address, username, password)

    # do cert rotation
    if not ARGS.report_only:
        if not os.path.isfile(ARGS.pkcs_file):
            raise ValueError(f'File "{ARGS.pkcs_file}" does not exist.')
        with open(ARGS.pkcs_file, 'rb') as file:
            file_bytes = file.read()
        try:
            client.authenticate()
            rotate_certs(client, file_bytes, ARGS.pkcs12_password, ARGS.friendly_name, fqdns, ARGS.shutdown_datastore,
                         ARGS.ack_datastore)
        except AuthenticationError:
            logging.error('Failed to authenticate the api client. Exiting.')
            sys.exit(1)
        except FailoverStateException:
            logging.error('The specified Manager is not the primary Manager for this deployment. Exiting.')
            sys.exit(1)
        except requests.exceptions.HTTPError:
            logging.error('An unexpected HTTP status was returned during certificate rotation. Exiting.')
            sys.exit(1)
        except (ApplianceStatusError, InvalidFqdnError, DataStoreStateError) as err:
            logging.error(f'{type(err).__name__}: {err}')
            logging.info('Exiting due to error conditions.')
            sys.exit(1)

    # monitor/report completion
    if ARGS.report or ARGS.report_only or ARGS.start_datastore:
        try:
            result = monitor_completion(client, fqdns, ARGS.friendly_name, ARGS.report_timeout)
        except FailoverStateException:
            logging.error('The specified Manager is not acting as the primary Manager for this deployment. Exiting.')
            sys.exit(1)
        if not result:
            sys.exit(1)

        # only start datastore if we've validated successful rotation of certificates
        if ARGS.start_datastore:
            if client.datastore_status()['status'] == 'down':
                logging.info('Starting Data Store...')
                client.start_datastore()
            else:
                logging.info('Data Store is not "down", so skipping "start" operation.')
