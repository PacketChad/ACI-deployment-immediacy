#!/usr/bin/env python3
"""
aci_update_static_port_immediacy.py
-------------------------------------
Updates the Deployment Immediacy setting for static port bindings
on a Cisco ACI EPG via the APIC REST API.

Inputs (via CLI args or interactive prompts):
  --apic         APIC hostname or IP
  --username     APIC username
  --password     APIC password  (prompted if omitted)
  --tenant       Tenant name
  --ap           Application Profile name
  --epg          EPG name
  --immediacy    Desired deployment immediacy: 'immediate' or 'lazy'
  --dry-run      Print the changes that would be made without applying them
  --no-verify    Disable SSL certificate verification (use for self-signed certs)

Examples:
  python3 aci_update_static_port_immediacy.py \
      --apic 10.0.0.1 --username admin \
      --tenant MyTenant --ap MyAP --epg MyEPG \
      --immediacy immediate

  # Dry run first to preview changes:
  python3 aci_update_static_port_immediacy.py \
      --apic 10.0.0.1 --username admin \
      --tenant MyTenant --ap MyAP --epg MyEPG \
      --immediacy lazy --dry-run
"""

import argparse
import re
import getpass
import json
import sys
import urllib.parse
import urllib.request
import ssl
import urllib.error


# ---------------------------------------------------------------------------
# HTTP helpers (no third-party dependencies required)
# ---------------------------------------------------------------------------

class ACISession:
    """Thin wrapper around urllib for APIC REST calls."""

    def __init__(self, apic: str, username: str, password: str, verify_ssl: bool = True):
        self.base_url = f"https://{apic}"
        self.verify_ssl = verify_ssl
        self.cookie = None
        self._ssl_ctx = ssl.create_default_context() if verify_ssl else self._unverified_ctx()
        self._login(username, password)

    @staticmethod
    def _unverified_ctx():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _request(self, method: str, path: str, payload: dict = None) -> dict:
        url = self.base_url + path
        data = json.dumps(payload).encode() if payload else None
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx) as resp:
                # Capture auth cookie on login
                set_cookie = resp.headers.get("Set-Cookie")
                if set_cookie and not self.cookie:
                    # Extract just the APIC-cookie value
                    for part in set_cookie.split(";"):
                        if "APIC-cookie" in part:
                            self.cookie = part.strip()
                            break
                    if not self.cookie:
                        self.cookie = set_cookie.split(";")[0].strip()
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            print(f"\n[ERROR] HTTP {e.code} on {method} {url}")
            print(f"        {body}")
            sys.exit(1)

    def _login(self, username: str, password: str):
        payload = {"aaaUser": {"attributes": {"name": username, "pwd": password}}}
        self._request("POST", "/api/aaaLogin.json", payload)
        if not self.cookie:
            print("[ERROR] Login succeeded but no session cookie was returned.")
            sys.exit(1)
        print(f"[OK] Logged in to {self.base_url}")

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def post(self, path: str, payload: dict) -> dict:
        return self._request("POST", path, payload)

    def logout(self):
        try:
            self._request("POST", "/api/aaaLogout.json",
                          {"aaaUser": {"attributes": {"name": ""}}})
        except Exception:
            pass
        print("[OK] Logged out.")


# ---------------------------------------------------------------------------
# ACI logic
# ---------------------------------------------------------------------------

VALID_IMMEDIACY = {"immediate", "lazy"}


def get_static_ports(session: ACISession, tenant: str, ap: str, epg: str) -> list:
    """
    Retrieve all fvRsPathAtt objects (static port bindings) for the given EPG.
    Returns a list of attribute dicts.
    """
    dn = f"uni/tn-{tenant}/ap-{ap}/epg-{epg}"
    path = (
        f"/api/mo/{urllib.parse.quote(dn)}.json"
        f"?query-target=children&target-subtree-class=fvRsPathAtt"
    )
    resp = session.get(path)
    imdata = resp.get("imdata", [])
    ports = []
    for item in imdata:
        if "fvRsPathAtt" in item:
            ports.append(item["fvRsPathAtt"]["attributes"])
    return ports


def update_static_port_immediacy(
    session: ACISession,
    tenant: str,
    ap: str,
    epg: str,
    ports: list,
    new_immediacy: str,
    dry_run: bool,
    node_filter: list = None,
):
    """
    For each static port whose deployImmediacy differs from new_immediacy,
    POST an update. Prints a summary of changes.
    """
    changed = 0
    skipped = 0

    for port in ports:
        tdn = port.get("tDn", "unknown")

        # Filter by node ID if --nodes was specified.
        # tDn format: topology/pod-X/paths-<NODE>/pathep-[...]
        if node_filter:
            # Extract node ID from tDn (the number after 'paths-')
            match = re.search(r"paths-(\d+)", tdn)
            node_id = match.group(1) if match else None
            if node_id not in node_filter:
                print(f"  [skip] {tdn}  (node {node_id} not in --nodes filter)")
                skipped += 1
                continue

        # instrImedcy is the correct ACI API attribute name for deployment immediacy
        # on fvRsPathAtt (static port bindings). Values: 'immediate' or 'lazy'.
        current = port.get("instrImedcy", "lazy")

        if current == new_immediacy:
            print(f"  [skip] {tdn}  (already '{current}')")
            skipped += 1
            continue

        print(f"  [{'DRY-RUN' if dry_run else 'update'}] {tdn}  "
              f"'{current}' → '{new_immediacy}'")

        if not dry_run:
            dn = port["dn"]
            payload = {
                "fvRsPathAtt": {
                    "attributes": {
                        "dn": dn,
                        "instrImedcy": new_immediacy,
                        "status": "modified",
                    }
                }
            }
            session.post(f"/api/mo/{urllib.parse.quote(dn)}.json", payload)
            changed += 1

    if dry_run:
        print(f"\n[DRY-RUN] {len(ports) - skipped} port(s) would be updated, "
              f"{skipped} already correct.")
    else:
        print(f"\n[DONE] {changed} port(s) updated, {skipped} already correct.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Update deployment immediacy for static ports in an ACI EPG."
    )
    p.add_argument("--apic",      required=True,  help="APIC hostname or IP")
    p.add_argument("--username",  required=True,  help="APIC username")
    p.add_argument("--password",                  help="APIC password (prompted if omitted)")
    p.add_argument("--tenant",    required=True,  help="Tenant name")
    p.add_argument("--ap",        required=True,  help="Application Profile name")
    p.add_argument("--epg",       required=True,  help="EPG name")
    p.add_argument(
        "--immediacy",
        required=True,
        choices=list(VALID_IMMEDIACY),
        help="Desired deployment immediacy: 'immediate' or 'lazy'",
    )
    p.add_argument(
        "--nodes",
        nargs="+",
        metavar="NODE_ID",
        help="Only process static ports on these node IDs (e.g. --nodes 101 102). "
             "Omit to target all nodes in the EPG.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="Disable SSL certificate verification (for self-signed certs)",
    )
    return p.parse_args()


def main():
    args = parse_args()

    password = args.password or getpass.getpass(f"Password for {args.username}@{args.apic}: ")

    print(f"\nTarget  : {args.tenant} / {args.ap} / {args.epg}")
    print(f"APIC    : {args.apic}")
    print(f"Setting : instrImedcy → '{args.immediacy}'")
    node_filter = [str(n) for n in args.nodes] if args.nodes else None
    if node_filter:
        print(f"Nodes   : {', '.join(node_filter)}")
    if args.dry_run:
        print("Mode    : DRY-RUN (no changes will be made)\n")
    else:
        print("Mode    : LIVE\n")

    session = ACISession(
        apic=args.apic,
        username=args.username,
        password=password,
        verify_ssl=not args.no_verify,
    )

    try:
        print(f"Fetching static ports for EPG '{args.epg}'...")
        ports = get_static_ports(session, args.tenant, args.ap, args.epg)

        if not ports:
            print("[WARN] No static port bindings (fvRsPathAtt) found for this EPG.")
            sys.exit(0)

        print(f"Found {len(ports)} static port(s):\n")
        update_static_port_immediacy(
            session=session,
            tenant=args.tenant,
            ap=args.ap,
            epg=args.epg,
            ports=ports,
            new_immediacy=args.immediacy,
            dry_run=args.dry_run,
            node_filter=[str(n) for n in args.nodes] if args.nodes else None,
        )
    finally:
        session.logout()


if __name__ == "__main__":
    main()