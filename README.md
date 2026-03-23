Update deployment immediacy for static ports in an ACI EPG.

Usage

```deployment-immediacy.py [-h] --apic APIC --username USERNAME [--password PASSWORD] --tenant TENANT --ap AP --epg EPG --immediacy {immediate,lazy} [--nodes NODE_ID [NODE_ID ...]] [--dry-run] [--no-verify]

options:
  -h, --help            show this help message and exit
  --apic APIC           APIC hostname or IP
  --username USERNAME   APIC username
  --password PASSWORD   APIC password (prompted if omitted)
  --tenant TENANT       Tenant name
  --ap AP               Application Profile name
  --epg EPG             EPG name
  --immediacy {immediate,lazy}
                        Desired deployment immediacy: 'immediate' or 'lazy'
  --nodes NODE_ID [NODE_ID ...]
                        Only process static ports on these node IDs (e.g. --nodes 101 102). Omit to target all nodes in the EPG.
  --dry-run             Preview changes without applying them
  --no-verify           Disable SSL certificate verification (for self-signed certs)
```


Examples:

Perform a dry run on a single node (101) with static ports in an EPG that are currently set to lazy/on-demand
```python deployment-immediacy.py --apic APIC --username USERNAME --password PASSWORD --tenant TENANT --ap AP --epg EPG --immediacy immediate --nodes 101 --dry-run --no-verify```

Perform a dry run on all nodes with static ports in an EPG that are currently set to lazy/on-demand
```python deployment-immediacy.py --apic APIC --username USERNAME --password PASSWORD --tenant TENANT --ap AP --epg EPG --immediacy immediate --dry-run --no-verify```

Perform an update on a single node (101) with static ports in an EPG that are currently set to lazy/on-demand
```python deployment-immediacy.py --apic APIC --username USERNAME --password PASSWORD --tenant TENANT --ap AP --epg EPG --immediacy immediate --nodes 101 --no-verify```

Perform an update on all nodes with static ports in an EPG that are currently set to lazy/on-demand
```python deployment-immediacy.py --apic APIC --username USERNAME --password PASSWORD --tenant TENANT --ap AP --epg EPG --immediacy immediate --no-verify```
