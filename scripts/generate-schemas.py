#!/usr/bin/env python3
"""Extract openAPIV3Schema from CRD YAMLs into kubeconform-compatible JSON schemas."""

import json
import sys
from pathlib import Path

import yaml

CRD_DIR = Path("manifests/base/crds")
SCHEMA_DIR = Path(".schemas")


def extract_schema(crd_path: Path) -> tuple[str, str, dict] | None:
    """Extract kind, version, and openAPIV3Schema from a CRD YAML."""
    with open(crd_path) as f:
        crd = yaml.safe_load(f)

    if crd.get("kind") != "CustomResourceDefinition":
        return None

    group = crd["spec"]["group"]
    kind = crd["spec"]["names"]["kind"]
    version_entry = crd["spec"]["versions"][0]
    version = version_entry["name"]
    schema = version_entry["schema"]["openAPIV3Schema"]

    # kubeconform expects a JSON Schema with x-kubernetes metadata
    schema["x-kubernetes-group-version-kind"] = [{"group": group, "kind": kind, "version": version}]

    api_version = f"{group}/{version}"
    return kind, api_version, schema


def main() -> None:
    SCHEMA_DIR.mkdir(exist_ok=True)

    crd_files = sorted(CRD_DIR.glob("*-crd.yaml"))
    if not crd_files:
        print(f"No CRD files found in {CRD_DIR}", file=sys.stderr)
        sys.exit(1)

    for crd_path in crd_files:
        result = extract_schema(crd_path)
        if result is None:
            continue

        kind, api_version, schema = result
        # kubeconform schema filename: <kind>_<apiVersion>.json
        # where apiVersion slashes become underscores
        filename = f"{kind.lower()}_{api_version.replace('/', '_')}.json"
        out_path = SCHEMA_DIR / filename

        with open(out_path, "w") as f:
            json.dump(schema, f, indent=2)

        print(f"  {crd_path.name} -> {out_path}")

    print(f"Generated {len(crd_files)} schemas in {SCHEMA_DIR}/")


if __name__ == "__main__":
    main()
