#!/usr/bin/env python3
"""Sign the final stapled archive for Sparkle; the private key stays in Keychain."""
import argparse
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fenlet import __version__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--description", default="Improvements to window arrangement, safety, and performance.")
    args = parser.parse_args()
    sparkle = subprocess.check_output(["bash", str(ROOT / "scripts/prepare-updater.sh")], text=True).strip()
    signature = subprocess.check_output([str(Path(sparkle) / "bin/sign_update"), "--account", "org.2018kguo.fenlet", "-p", str(args.archive)], text=True).strip()
    subprocess.run([str(Path(sparkle) / "bin/sign_update"), "--account", "org.2018kguo.fenlet", "--verify", str(args.archive), signature], check=True)
    ns = "http://www.andymatuschak.org/xml-namespaces/sparkle"
    ET.register_namespace("sparkle", ns)
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Fenlet updates"
    ET.SubElement(channel, "link").text = "https://github.com/2018kguo/fenlet/releases"
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = "Fenlet " + __version__
    ET.SubElement(item, "pubDate").text = format_datetime(datetime.now(timezone.utc))
    for name, value in (("version", __version__), ("shortVersionString", __version__), ("minimumSystemVersion", "13.0"), ("hardwareRequirements", "arm64")):
        ET.SubElement(item, "{" + ns + "}" + name).text = value
    ET.SubElement(item, "description").text = args.description
    ET.SubElement(item, "enclosure", {"url": f"https://github.com/2018kguo/fenlet/releases/download/v{__version__}/{args.archive.name}",
        "length": str(args.archive.stat().st_size), "type": "application/octet-stream", "{" + ns + "}edSignature": signature,
        "{" + ns + "}os": "macos"})
    ET.indent(root)
    path = ROOT / "docs/appcast.xml"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    print(path)


if __name__ == "__main__": main()
