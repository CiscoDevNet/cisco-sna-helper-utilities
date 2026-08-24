Splunk Setup Guide for NDR Egress Service (SNA 7.6.1)
August 2026


Step 1 - Set up Splunk to receive syslog from Egress Service

1. Log into Splunk Web as Administrator.
2. Go to Settings > Data Inputs > UDP.
3. Click New.
4. Set port to 514 (or the port your Egress Service syslog is configured to send to).
5. Set Source type to: svc_ndr_adapter_flow
6. Save.

If port 514 fails with "UDP port 514 is not available":

    cd /opt/splunk/bin
    sudo ./splunk start --accept-license

Check if the port is already in use:

    netstat -nlup    (for UDP)
    netstat -nltp    (for TCP)


Step 2 - Install props.conf

Copy props.conf to:

    $SPLUNK_HOME/etc/system/local/props.conf

Or inside your Splunk app:

    $SPLUNK_HOME/etc/apps/<your_app>/local/props.conf

The props.conf file defines the sourcetype svc_ndr_adapter_flow and maps the CSV
field order to named fields matching the NDR Egress Service source code.


Step 3 - Install transforms.conf

Copy transforms.conf to:

    $SPLUNK_HOME/etc/system/local/transforms.conf

Or inside your Splunk app:

    $SPLUNK_HOME/etc/apps/<your_app>/local/transforms.conf

The transforms.conf file auto-assigns the sourcetype based on the event pattern
and provides a fallback DELIMS-based extraction for older Splunk versions.


Step 4 - Restart Splunk

    cd /opt/splunk/bin
    sudo ./splunk restart


Step 5 - Verify in Splunk

1. Go to Search and Reporting.
2. Run the search:

    index=* sourcetype=svc_ndr_adapter_flow

3. You should now see parsed human-readable fields in the left panel:
   client_ip, server_ip, protocol, client_num_bytes, server_num_bytes,
   client_port, server_port, username, start_active_usec, etc.


Field Reference

The following fields are extracted in order from each CSV flow record:

    hostname, flow_id, sequence_num,
    client_total_bytes, client_total_packets,
    server_total_bytes, server_total_packets, total_bytes,
    client_ip, server_ip, fc_ip,
    client_tls_version, start_active_usec, last_active_usec,
    client_group_list, server_group_list,
    client_payload, server_payload,
    protocol, flow_sensor_app_id,
    client_mac, server_mac,
    client_port, server_port,
    client_num_bytes, server_num_bytes,
    client_num_packets, server_num_packets,
    client_xlate_ip, server_xlate_ip,
    client_xlate_port, server_xlate_port,
    vlan_id, username,
    client_exporters, server_exporters,
    client_interfaces, server_interfaces


Note on field naming

Field names appear exactly as listed above. Customers can rename them by editing
the FIELD_NAMES line in props.conf to use their own naming convention (for
example, adding a SW_ prefix or any other prefix).


Troubleshooting

Raw CSV still showing after install:
- Confirm sourcetype is set to svc_ndr_adapter_flow on the UDP input.
- Confirm props.conf and transforms.conf are in the correct local/ directory.
- Restart Splunk after any config file changes.

No events appearing:
- Confirm Egress Service syslog exporter is enabled and pointing to the correct
  Splunk host and port.
- Check Splunk internal logs: index=_internal sourcetype=splunkd error

Port 514 permission denied:
- Run Splunk with sudo (see Step 1 above).
- Or use a port above 1024 (e.g. 5514) which does not require root privileges.
