#!/usr/bin/env python3
"""
aci_update_static_port_immediacy.py
-------------------------------------
Updates the Deployment Immediacy setting for static port bindings
on a Cisco ACI EPG via the APIC REST API.

Supports:
  - Targeting specific EPGs manually.
  - Auto-discovering all EPGs on specific Nodes.
  - Dry-run mode and SSL verification toggle.
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
                set_cookie = resp.headers.get("Set-Cookie")
                if set_cookie and not self.cookie:
                    for part in set_cookie.split(";"):
                        if "APIC-cookie" in part:
                            self.cookie = part.strip()
                            break
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
# ACI Logic & Discovery
# ---------------------------------------------------------------------------

def discover_epgs_on_nodes(session: ACISession, node_ids: list) -> set:
    """
    Queries the APIC for all EPGs that have static paths on the given nodes.
    Returns a set of tuples: (tenant, app_profile, epg)
    """
    discovered_targets = set()
    
    for node in node_ids:
        # Filter for paths containing the specific node ID within the DN
        query_path = (
            f"/api/class/fvRsPathAtt.json?"
            f"query-target-filter=wcard(fvRsPathAtt.dn,\"paths-{node}/\")"
        )
        
        resp = session.get(query_path)
        imdata = resp.get("imdata", [])
        
        for item in imdata:
            dn = item["fvRsPathAtt"]["attributes"]["dn"]
            # Extract Tenant, AP, and EPG names from the DN structure
            match = re.search(r"tn-([^/]+)/ap-([^/]+)/epg-([^/]+)", dn)
            if match:
                discovered_targets.add(match.groups())
                
    return discovered_targets


def get_static_ports(session: ACISession, tenant: str, ap: str, epg: str) -> list:
    """Retrieve all fvRsPathAtt objects for the given EPG."""
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
    ports: list,
    new_immediacy: str,
    dry_run: bool,
    node_filter: list = None,
):
    """Updates deployment immediacy if current state differs."""
    changed = 0
    skipped = 0

    for port in ports:
        tdn = port.get("tDn", "unknown")

        if node_filter:
            match = re.search(r"paths-(\d+)", tdn)
            node_id = match.group(1) if match else None
            if node_id not in node_filter:
                skipped += 1
                continue

        current = port.get("instrImedcy", "lazy")

        if current == new_immediacy:
            skipped += 1
            continue

        print(f"    [{'DRY-RUN' if dry_run else 'update'}] {tdn} | '{current}' → '{new_immediacy}'")

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

    return changed, skipped


# ---------------------------------------------------------------------------
# CLI & Execution
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Update ACI static port deployment immediacy.")
    p.add_argument("--apic",      required=True,  help="APIC hostname or IP")
    p.add_argument("--username",  required=True,  help="APIC username")
    p.add_argument("--password",                  help="APIC password")
    p.add_argument("--tenant",                    help="Tenant name (required if not using discovery)")
    p.add_argument("--ap",                        help="App Profile name (required if not using discovery)")
    p.add_argument("--epg",       nargs="+",      help="EPG name(s). If omitted, --nodes is used for discovery.")
    p.add_argument("--immediacy", required=True,  choices=["immediate", "lazy"])
    p.add_argument("--nodes",     nargs="+",      help="Node IDs to filter or discover (e.g. 101 102)")
    p.add_argument("--dry-run",   action="store_true", help="Preview changes")
    p.add_argument("--no-verify", action="store_true", help="Disable SSL verification")
    return p.parse_args()


def main():
    args = parse_args()
    password = args.password or getpass.getpass(f"Password for {args.username}@{args.apic}: ")
    node_filter = [str(n) for n in args.nodes] if args.nodes else None

    session = ACISession(args.apic, args.username, password, not args.no_verify)

    try:
        # Determine targets: either manual CLI input or auto-discovery based on nodes
        if node_filter and not args.epg:
            print(f"Discovering EPGs on nodes: {', '.join(node_filter)}...")
            targets = discover_epgs_on_nodes(session, node_filter)
        elif args.tenant and args.ap and args.epg:
            targets = [(args.tenant, args.ap, e) for e in args.epg]
        else:
            print("[ERROR] Provide --tenant, --ap, and --epg OR provide --nodes for discovery.")
            sys.exit(1)

        if not targets:
            print("[WARN] No EPGs identified for processing.")
            return

        print(f"Found {len(targets)} EPG(s) to process.\n")

        for t_name, a_name, e_name in targets:
            print(f"Processing EPG: {t_name} | {a_name} | {e_name}")
            ports = get_static_ports(session, t_name, a_name, e_name)
            
            if not ports:
                print("  [skip] No static ports found.")
                continue

            changed, skipped = update_static_port_immediacy(
                session, ports, args.immediacy, args.dry_run, node_filter
            )
            print(f"  Summary: {changed} updated, {skipped} unchanged/filtered.")

    finally:
        session.logout()

if __name__ == "__main__":
    main()