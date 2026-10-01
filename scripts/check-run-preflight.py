#!/usr/bin/env python3
"""Fail closed when another subscription-scoped run or overlapping VNet exists."""

import ipaddress
import json
import sys

FEATURES = {"Connectivity", "SecurityAdmin", "Routing"}
ROOT = ipaddress.ip_network("172.20.0.0/14")


def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get("subscriptionId"), str):
        raise ValueError("Missing subscription ID")
    subscription = f"/subscriptions/{data['subscriptionId']}".lower()
    managers, vnets = data.get("managers"), data.get("vnets")
    if not isinstance(managers, list) or not isinstance(vnets, list):
        raise ValueError("Invalid AVNM or VNet inventory")
    for manager in managers:
        if not isinstance(manager, dict):
            raise ValueError("Invalid AVNM inventory entry")
        accesses, scopes = manager.get("networkManagerScopeAccesses"), manager.get("networkManagerScopes")
        if not isinstance(accesses, list) or any(not isinstance(a, str) for a in accesses):
            raise ValueError("Invalid AVNM feature access list")
        if not isinstance(scopes, dict):
            raise ValueError("Invalid AVNM scope")
        subscriptions, groups = scopes.get("subscriptions"), scopes.get("managementGroups")
        if not isinstance(subscriptions, list) or not isinstance(groups, list):
            raise ValueError("Invalid AVNM subscription or management group scope")
        if any(not isinstance(s, str) for s in subscriptions + groups):
            raise ValueError("Invalid AVNM scope ID")
        if FEATURES.intersection(accesses) and (
            any(s.lower() == subscription for s in subscriptions) or groups
        ):
            raise ValueError("Another AVNM may own this subscription's workshop features")
    for vnet in vnets:
        if not isinstance(vnet, dict) or not isinstance(vnet.get("addressSpace"), dict):
            raise ValueError("Invalid VNet inventory entry")
        prefixes = vnet["addressSpace"].get("addressPrefixes")
        if not isinstance(prefixes, list) or not prefixes:
            raise ValueError("Missing VNet address prefixes")
        for prefix in prefixes:
            if not isinstance(prefix, str):
                raise ValueError("Invalid VNet address prefix")
            network = ipaddress.ip_network(prefix, strict=True)
            if network.version == 4 and network.overlaps(ROOT):
                raise ValueError(f"Existing VNet overlaps the workshop IPAM root: {vnet.get('id', 'unknown')}")


if __name__ == "__main__":
    try:
        validate(json.load(sys.stdin))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: Run subscription preflight failed: {exc}", file=sys.stderr)
        sys.exit(1)
