Update deployment immediacy for static ports in an ACI EPG \
\
\
```
options:
  -h, --help            show this help message and exit
  --apic APIC           APIC hostname or IP
  --username USERNAME   APIC username
  --password PASSWORD   APIC password (prompted if omitted)
  --tenant TENANT       Tenant name (required if not using discovery)
  --ap AP               App Profile name (required if not using discovery)
  --epg EPG             EPG name(s). If omitted, --nodes is used for discovery.
  --immediacy {immediate,lazy}
                        Desired deployment immediacy: 'immediate' or 'lazy'
  --nodes NODE_ID [NODE_ID ...]
                        Node IDs to filter or discover (e.g. 101 102)
  --dry-run             Preview changes without applying them
  --no-verify           Disable SSL certificate verification (for self-signed certs)
```
