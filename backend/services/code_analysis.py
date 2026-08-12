"""
Code / architecture insight extraction.

HMGCC Q&A Q14: code analysis isn't a priority for this challenge, but
"basic architectural insights" are useful:
  - High level component design listing:
    - Firmware modules (bootloader, kernel, drivers, OTA updater)
    - Communication interfaces (UART, I2C, SPI, Ethernet, Wi-Fi etc)
    - Trusted and untrusted execution domains
    - External dependencies (libs, 3rd party SDKs)
    - Attack surfaces (ports, exposed APIs, filesystem mounts)

This module scans plain-text source files for these signals using
keyword/regex heuristics - deliberately lightweight, no compilation or
execution of uploaded code, consistent with Q&A Q21 (no binaries/firmware
expected in test data) and the general low-priority framing of this
capability.
"""

from __future__ import annotations

import json
import re
from typing import List

CODE_SUFFIXES = {
    ".c", ".h", ".cpp", ".hpp", ".cc", ".py", ".js", ".ts", ".java", ".go",
    ".rs", ".rb", ".php", ".cs", ".swift", ".kt", ".sh", ".ino",
}
MANIFEST_FILES = {
    "requirements.txt", "package.json", "pyproject.toml",
    "cargo.toml", "go.mod", "cmakelists.txt", "makefile", "pom.xml", "build.gradle",
}

FIRMWARE_MODULE_KEYWORDS = {
    "bootloader": "Bootloader", "kernel": "Kernel", "driver": "Driver",
    "ota update": "OTA updater", "over-the-air": "OTA updater", "rtos": "RTOS",
    "hal.": "Hardware Abstraction Layer", "firmware update": "Firmware updater",
}

COMM_INTERFACE_KEYWORDS = {
    "uart": "UART", "i2c": "I2C", "spi": "SPI", "ethernet": "Ethernet",
    "wi-fi": "Wi-Fi", "wifi": "Wi-Fi", "bluetooth": "Bluetooth", " ble ": "BLE",
    "can bus": "CAN bus", "canbus": "CAN bus", "modbus": "Modbus",
    "usb": "USB", "gpio": "GPIO", "rs-485": "RS-485", "rs485": "RS-485",
    "zigbee": "Zigbee", "lora": "LoRa", "tcp/ip": "TCP/IP", "mqtt": "MQTT",
}

TRUST_DOMAIN_KEYWORDS = {
    "trustzone": "ARM TrustZone (trusted execution)", "secure boot": "Secure boot",
    "trusted execution": "Trusted execution environment",
    "untrusted": "Untrusted execution domain", "sandbox": "Sandboxed execution",
    "privilege": "Privilege boundary",
}

ATTACK_SURFACE_PATTERNS = [
    (re.compile(r'\.(listen|bind)\s*\(', re.IGNORECASE), "Open network listener"),
    (re.compile(r'\.run\s*\(\s*host\s*=\s*["\']0\.0\.0\.0', re.IGNORECASE), "Open network listener"),
    (re.compile(r'@(app|router)\.(get|post|put|delete|patch)\s*\(', re.IGNORECASE), "Exposed API route"),
    (re.compile(r'\bopen\s*\(\s*["\'](?:/dev/|/proc/|/sys/)', re.IGNORECASE), "Filesystem/device mount access"),
    (re.compile(r'(password|secret|api[_-]?key|token)\s*[=:]\s*["\'][^"\']{4,}["\']', re.IGNORECASE), "Possible hardcoded secret"),
    (re.compile(r'\bexec(ute)?\s*\(|os\.system\s*\(|subprocess\.', re.IGNORECASE), "Command execution surface"),
]


def is_code_file(suffix: str, filename: str) -> bool:
    return suffix.lower() in CODE_SUFFIXES or filename.lower() in MANIFEST_FILES


def analyse_source(text: str, filename: str = "") -> dict:
    """Return a structured architecture-insight report for one file's text."""
    lower = f" {text.lower()} "
    fname_lower = filename.lower()

    firmware_modules = sorted({label for kw, label in FIRMWARE_MODULE_KEYWORDS.items() if kw in lower})
    comm_interfaces = sorted({label for kw, label in COMM_INTERFACE_KEYWORDS.items() if kw in lower})
    trust_domains = sorted({label for kw, label in TRUST_DOMAIN_KEYWORDS.items() if kw in lower})

    attack_surfaces: List[str] = []
    for pattern, label in ATTACK_SURFACE_PATTERNS:
        if pattern.search(text):
            attack_surfaces.append(label)

    dependencies = _parse_manifest(fname_lower, text) if fname_lower in MANIFEST_FILES else []

    return {
        "firmware_modules": firmware_modules,
        "comm_interfaces": comm_interfaces,
        "trust_domains": trust_domains,
        "attack_surfaces": sorted(set(attack_surfaces)),
        "external_dependencies": dependencies,
    }


def _parse_manifest(fname_lower: str, text: str) -> List[str]:
    deps: List[str] = []
    try:
        if fname_lower == "requirements.txt":
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    deps.append(re.split(r'[=<>~!\[;]', line)[0].strip())
        elif fname_lower == "package.json":
            data = json.loads(text)
            for section in ("dependencies", "devDependencies"):
                deps.extend(data.get(section, {}).keys())
        elif fname_lower == "go.mod":
            for m in re.finditer(r'^\s*require\s+([^\s]+)', text, re.MULTILINE):
                deps.append(m.group(1))
            for m in re.finditer(r'^\s{2,}([^\s]+)\s+v[\d.]+', text, re.MULTILINE):
                deps.append(m.group(1))
        elif fname_lower == "cargo.toml":
            in_deps = False
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("[dependencies"):
                    in_deps = True
                    continue
                if stripped.startswith("[") and in_deps:
                    in_deps = False
                if in_deps and "=" in stripped:
                    deps.append(stripped.split("=")[0].strip())
    except Exception:
        pass
    return sorted({d for d in deps if d})


def format_report(report: dict, filename: str) -> str:
    """Render the structured report as readable text for indexing/citation."""
    lines = [f"[Architecture insight report: {filename}]"]
    if report["firmware_modules"]:
        lines.append("Firmware modules detected: " + ", ".join(report["firmware_modules"]))
    if report["comm_interfaces"]:
        lines.append("Communication interfaces detected: " + ", ".join(report["comm_interfaces"]))
    if report["trust_domains"]:
        lines.append("Trust/execution domain signals: " + ", ".join(report["trust_domains"]))
    if report["attack_surfaces"]:
        lines.append("Potential attack surfaces: " + ", ".join(report["attack_surfaces"]))
    if report["external_dependencies"]:
        lines.append("External dependencies: " + ", ".join(report["external_dependencies"]))
    if len(lines) == 1:
        lines.append("No architectural signals detected by heuristic scan.")
    return "\n".join(lines)
