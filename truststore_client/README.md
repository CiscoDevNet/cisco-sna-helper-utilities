# Secure Network Analytics (SNA) Trust Store Management Exemplar Script

This script is a standalone, exemplar/starter script that can be used to manage Trust Stores of SNA appliances.

When running the script, the user:
- provides a PEM file with a single certificate
- specifies a list of appliances (by FQDN) on which to perform the operation
- specifies the action to perform (add certificate, delete certificate, check presence of certificate)
 
Additional options and details are noted in the Usage section.

Note that the script halts execution when an error is encountered - so users can intervene and troubleshoot/resolve
any issues as needed. The script can be run again against the outstanding appliances (provide this subset of appliances
using the `--fqdns` argument). This subset of appliances can be inferred from the script's output, from inspecting
the SNA deployment, or by running the script with the `--action check` argument.

## Limitations

1. This script currently only supports using a PEM file with a single certificate.
2. This script currently assumes correctness of the provided PEM file (does not perform PEM file validation).

## Usage

### Prerequisites

**Runtime**
1. Setup python environment with packages listed in requirements.txt. Testing was performed using Python 3.13.1. 
2. Configure the python requests library to use the root CA certificate of your SNA primary Manager appliance identity 
certificate chain, such as by placing that certificate on disk and running 
`export REQUESTS_CA_BUNDLE=<path-to-root-CA-cert>`.  Alternatively, you can provide the --verify-false parameter during
script execution to disable SSL certificate verification (not recommended).
3. Setup authentication, such as by exporting credentials (see below) or by replacing the `_get_credentials` method in
the script (and performing any necessary steps)
```
export USERNAME=<username>
export PASSWORD=<password>
```

### Sample Commands

Add a certificate to Trust Stores of all appliances in the deployment
```
./update-truststores.py -m sna-manager.example.com -f ca.pem --fqdns all
```

Delete a certificate from Trust Stores of all appliances in the deployment
```
./update-truststores.py -m sna-manager.example.com -f ca.pem --fqdns all --action del
```

Inspect Trust Stores of all appliances in the deployment for presence of a certificate
```
./update-truststores.py -m sna-manager.example.com -f ca.pem --fqdns all --action check
```

Add a certificate to Trust Stores of specific appliances
```
./update-truststores.py -m sna-manager.example.com -f ca.pem --fqdns sna-fc.example.com sna-fs.example.com
```

To specify a friendly name to use for the certificate in the Trust Stores, include the --friendly-name <name> argument.
To enable debug logging, include the -d/--debug argument.
To change the timeout period for monitoring the state of Trust Stores, specify -t/--monitor-timeout <seconds>. This argument defaults to 1800.

## Troubleshooting

### Error Messages

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
Typically this will be uncaught when SNA rejects the Trust Store update.

HTTP 400s might indicate that the certificate (or a conflicting certificate) is already present in the Trust Store.

HTTP 409s typically occur if a Central Management configuration operation has been triggered simultaneously while 
the script is attempting to configure the appliance. Review the status of the relevant appliance in Central Management
and try again when the appliance status shows "Connected" and additional configuration changes are not expected.

Review `/lancope/var/logs/containers/svc-central-management.log` for potential details.

#### Other Python Requests errors
Review error details and connectivity to the SNA Manager appliance from your execution environment.

## Customizations and Enhancement

### Authentication / credential retrieval
Optionally rewrite the `_get_credentials` method to retrieve credentials from a different source than environment variables.

### PEM file validation
Validate the correctness of the provided PEM file before sending to appliances.

### Support other certificate file formats and/or adding multiple certificates from a file.
(self-explanatory)

### Do not halt execution on failure
Consider allowing operations to proceed on other appliances. Consider ignoring certain benign failures (e.g. cert 
already present).

### Log details of which certificate is being added/deleted/checked
(self-explanatory)

### Other improvements to consider
- Improve logic used for deciding when to refresh tokens
- Consider handling HTTP 409s differently, such as by retrying the operation
- Log more details about HTTP errors
