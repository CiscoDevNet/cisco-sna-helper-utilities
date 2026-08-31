# cisco-sna-helper-utilities

This repo contains helper utilities for users of Cisco Secure Network Analytics (SNA). 

Distinct utilities are currently provided in individual subfolders, where READMEs and dependency files can be found for each tool.

### Available Utilities

| Utility                                        | Description                                                                                                                                                                                         |
|------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [cert_rotation_client](./cert_rotation_client) | This utility automates the installation of a provided identity certificate on specified SNA appliances. View its [README](./cert_rotation_client/README.md) for more details.                       |
| [host_group_automation_csv_import](./host_group_automation_csv_import) | This utility imports host groups and their IP ranges from CSV data using the SNA Host Group Automation API. View its [README](./host_group_automation_csv_import/README.md) for more details. |
| [truststore_client](./truststore_client)       | This utility facilitates the management of SNA appliance Trust Stores, including addition, removal, and listing of certificates. View its [README](./truststore_client/README.md) for more details. |
| [egress_service_config_cli](./egress_service_config_cli) | This utility remotely configures the SNA Egress Service (`svc-ndr-adapter`) on a Flow Collector via its REST API, covering health checks, exporter status, syslog configuration, and reset. View its [README](./egress_service_config_cli/README.md) for more details. |
| [splunk_flow_export](./splunk_flow_export)     | This utility documents how to configure Splunk to receive and parse NDR Egress Service flow export data (props.conf and transforms.conf included). View its [README](./splunk_flow_export/README.md) for more details. |

### Project Information

For more information about the project, please see:
- `AGENTS.md`: Guidance for AI coding agents working in this repository.
- `CODE_OF_CONDUCT.md`: Community standards for participation.
- `CONTRIBUTING.md`: Contribution and collaboration guidance.
- `SECURITY.md`: Security reporting and disclosure guidance.
