# Secure Network Analytics (SNA) Appliance Identity Certificate Rotation Exemplar Script

This script is a standalone, exemplar/starter script that installs a provided identity certificate to SNA appliances. 
Its primary use is to install a single/shared identity certificate to multiple SNA appliances in a deployment.

When running the script, the user provides a PKCS12 file and a list of appliances (by FQDN) on which to install the 
identity certificate bundle. The script can optionally poll the SNA deployment for completion of certificate rotation. 
Additional options and details are listed in the Usage section.

Note that the script halts execution when an error in certificate rotation is encountered - so users can intervene and 
troubleshoot/resolve any issues as needed. The script can be run again against the outstanding appliances (provide this 
subset of appliances using the `--fqdns` argument). This subset of appliances can be inferred from the script's output, 
from inspecting the SNA deployment, or by running the script with the `-ro` argument.

## Limitations
1. This script is written for SNA 7.5.x. Running this script against earlier SNA releases can cause inter-appliance
communication outages that may require Cisco Support to resolve.
2. This script assumes the provided PKCS12 bundle is correctly constructed in alignment with SNA PKCS12 bundle 
requirements. Though SNA (7.5.x) will prevent installation of a misconfigured bundle, this script does not inspect the 
bundle for correctness before attempting to install to SNA. 
3. This script assumes the root CA certificate is already installed in the SNA appliances' Trust Stores, but it does not
validate that assumption. Failure to meet this precondition could cause script failure and/or communication outages in
the management channels between SNA appliances, requiring Cisco Support to resolve. 

## Warnings
1. Rotating an SNA appliance's identity certificate currently causes that appliance to reboot. Consequently, this script
will cause targeted appliances to reboot (without warning).
2. If this script is run against Data Node appliances, the Data Store will either need to be shutdown or will be running
in a weakened state.  See more details in the Prerequisites > Data Store section. 
3. Even if Data Store shutdown/startup is managed by this script (via cli args), errors or timeouts during monitor can 
leave the Data Store in a shutdown state. 
4. If the relevant root CA certificate is not installed on peer appliances (other appliances in the deployment) prior to
script execution, communication outages between appliances will occur (see Limitations).

## Usage

### Prerequisites

**Runtime**
1. Setup python environment with packages listed in requirements.txt. Testing was performed using Python 3.13.1. 
2. Configure the python requests library to use the root CA certificate of your SNA primary Manager appliance identity 
certificate chain, such as by placing that certificate on disk and running 
`export REQUESTS_CA_BUNDLE=<path-to-root-CA-cert>`
3. Setup authentication, such as by exporting credentials (see below) or by replacing the `_get_credentials` method in
the script (and performing any necessary steps)
```
export USERNAME=<username>
export PASSWORD=<password>
```

**Data Store**
If the target deployment contains a Data Store, specific Data Store requirements apply:
- If the SNA deployment contains only one Data Node appliance, the Data Store must be shut down before certificate 
rotation occurs.
- If the SNA deployment contains multiple Data Node appliances, it is optional but recommended to shut down the Data Store.

If the Data Store is left "up" during certificate rotation, individual Data Node appliances will need to re-join the DB
and perform recovery operations (both automatic) after they reboot. While one Data Node is rebooting/recovering, other 
nodes are vital to the Data Store health. Generally, it is recommended to shut down the Data Store before rebooting any 
Data Nodes to avoid such issues.

Users can manually stop/start the Data Store before running this script, or the user can provide specific script args 
to have the script perform Data Store shutdown and startup.

### Sample Commands

Apply the certificate bundle to all appliances in the deployment (no Data Store in deployment)
```
./update-identity.py -m sna-manager.example.com -f new-identity-bundle.pfx -p password --fqdns all
```

Apply the certificate bundle to all appliances in the deployment (no Data Store in deployment) and monitor completion:
```
./update-identity.py -m sna-manager.example.com -f new-identity-bundle.pfx -p password --fqdns all -r
```

Apply the certificate bundle to all appliances in the deployment (stop and start Data Store)
```
./update-identity.py -m sna-manager.example.com -f new-identity-bundle.pfx -p password --fqdns all --shutdown-datastore --start-datastore
```

Apply the certificate bundle to all appliances in the deployment (without shutting down Data Store - multi-node only)
```
./update-identity.py -m sna-manager.example.com -f new-identity-bundle.pfx -p password --fqdns all --ack-datastore
```

Apply the certificate bundle for specific appliances
```
./update-identity.py -m sna-manager.example.com -f new-identity-bundle.pfx -p password --fqdns sna-fc.example.com sna-fs.example.com
```

Only check completion of certificate rotation for all appliances in the deployment, using a specific friendly-name
(such as to evaluate a prior run; supply the friendly-name that was supplied or generated during that prior run):
```
./update-identity.py -m sna-manager.example.com --fqdns all -ro --friendly-name 2025-04-cert
```

## Troubleshooting

### Error Messages

#### DataStoreStateError
Data Store state disallows operations, such as because:
- the data store is "up" and the user hasn't provided the `--ack-datastore argument` (multi-node data store only)
- the data store is "up" and the user hasn't provided the `--shutdown-datastore` argument
- the `--shutdown-datastore argument` was provided but the data store failed to stop properly within an allocated timeout
- Central Management is otherwise disallowing Data Store actions (review the `allowDataStoreApplianceActions` for 
relevant Data Node appliances in Central Management)

#### ApplianceStatusError

The target appliance does not have a "Connected" status in Central Management. Bring the appliance to the "Connected" 
state and try again. In rare cases, the target appliance may be "Connected" but the script may be unable to find its 
`id` attribute in its json object representation.

### Exceptions

Specific exceptions are not caught by the script so all error details propagate to the user.  If the following 
exceptions are thrown, consider the corresponding suggested troubleshooting steps.

#### requests.exceptions.SSLError
This may be thrown if `REQUESTS_CA_BUNDLE` is not set correctly or if the manager address (`-m`) is not present in the 
current SNA Manager appliance identity certificate. Ensure `REQUESTS_CA_BUNDLE` is set properly and that the manager 
address is present in the SNA Manager's current appliance identity certificate.

#### requests.exceptions.HTTPError
Typically this will be uncaught when SNA rejects the certificate rotation requests.

HTTP 400s typically indicate a problem with certificate rotation requests, most commonly:
- the pkcs12 password is wrong
- the pkcs12 bundle was built incorrectly with regard to SNA certificate bundle requirements
- the target appliance does not have the relevant root CA certificate in its Trust Store

HTTP 409s typically occur if a Central Management configuration operation has been triggered simultaneously while 
the script is attempting to configure (rotate certificates) for the appliance. Review the status of the relevant 
appliance in Central Management and try again when the appliance status shows "Connected" and additional configuration 
changes are not expected.

Review `/lancope/var/logs/containers/svc-central-management.log` for potential details.

#### Other Python Requests errors
Review error details and connectivity to the SNA Manager appliance from your execution environment.

## Customizations and Enhancement

### Authentication / credential retrieval
Optionally rewrite the `_get_credentials` method to retrieve credentials from a different source than environment variables.

### Command line argument validation
Additional command line argument validations could be added to handle issues earlier in script execution and more clearly,
such as:
- analyze the correctness of the pkcs12 file
- check the correctness of the pkcs12 password

### Other improvements to consider
- Improve logic used for deciding when to refresh tokens
- Consider handling HTTP 409s differently, such as by retrying the operation
- Log more details about HTTP errors
