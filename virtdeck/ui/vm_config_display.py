from .i18n import tr, tr_dict

# Labels for config keys
HW_LABELS = tr_dict(lambda: {
    "name": tr("Name"),
    "cpu": tr("CPU type"),
    "cores": tr("Cores"),
    "sockets": tr("Sockets"),
    "memory": tr("Memory"),
    "bios": tr("BIOS"),
    "machine": tr("Chipset"),
    "vga": tr("VGA"),
    "scsihw": tr("SCSI controller"),
    "vmgenid": tr("VM Generation ID"),
    "ostype": tr("OS type"),
    "acpi": tr("ACPI"),
    "agent": tr("QEMU Agent"),
    "kvm": tr("KVM (nested virtualization)"),
    "tablet": tr("USB Tablet"),
    "boot": tr("Boot"),
    "bootdisk": tr("Boot disk"),
    "onboot": tr("Start on boot"),
    "startup": tr("Startup order"),
    "numa": tr("NUMA"),
    "hotplug": tr("Hotplug"),
    "freeze": tr("Freeze (pause at start)"),
    "keyboard": tr("Keyboard layout"),
    "localtime": tr("Local time"),
    "protection": tr("Delete protection"),
    "reboot": tr("Reboot after crash"),
    "rtc": tr("RTC"),
    "smbios1": tr("SMBIOS"),
    "tags": tr("Tags"),
    "tdf": tr("TDF"),
    "template": tr("Template"),
    "vcpus": tr("Virtual CPUs (hotplug)"),
    "spice": tr("SPICE"),
    "spice_enhancements": tr("SPICE enhancements"),
    "args": tr("Extra QEMU args"),
    "hookscript": tr("Hook script"),
    "running-machine": tr("Chipset (running)"),
    "efidisk0": tr("EFI disk"),
    "tpmstate0": tr("TPM"),
})

_DEVICE_PREFIX_LABELS = tr_dict(lambda: {
    "net": tr("Network"),
    "ide": tr("IDE"),
    "sata": tr("SATA"),
    "scsi": tr("SCSI"),
    "virtio": tr("Hard disk"),
    "efidisk": tr("EFI disk"),
    "tpmstate": tr("TPM"),
    "usb": tr("USB"),
    "hostpci": tr("PCI"),
    "serial": tr("Serial port"),
})


def _device_label(key, value=None):
    prefix = key.rstrip("0123456789")
    num = key[len(prefix):]
    base = _DEVICE_PREFIX_LABELS.get(prefix, prefix)
    if prefix == "ide" and num == "2":
        return tr("Optical drive")
    if value is not None and _is_cdrom_value(value) and prefix in ("ide", "sata", "scsi"):
        return tr("Optical drive")
    if prefix in ("virtio", "scsi", "sata", "ide", "usb", "hostpci", "serial", "net"):
        if num:
            return f"{base} ({prefix}{num})"
        return base
    if num:
        return f"{base} {num}"
    return base


CHOICE_LABELS = tr_dict(lambda: {
    "cpu": {
        "kvm64": tr("KVM64 (compatible)"),
        "host": tr("Host (maximum)"),
        "qemu64": tr("QEMU64"),
        "max": tr("Host (max, risky)"),
        "x86-64-v2": tr("x86-64 v2"),
        "x86-64-v2-AES": tr("x86-64 v2 + AES"),
        "x86-64-v3": tr("x86-64 v3"),
        "x86-64-v3-AES": tr("x86-64 v3 + AES"),
        "x86-64-v4": tr("x86-64 v4"),
        "x86-64-v4-AES": tr("x86-64 v4 + AES"),
    },
    "bios": {
        "seabios": tr("SeaBIOS"),
        "ovmf": tr("OVMF (UEFI)"),
    },
    "machine": {
        "i440fx": tr("i440fx"),
        "q35": tr("Q35"),
    },
    "vga": {
        "std": tr("VGA (standard)"),
        "qxl": tr("QXL (SPICE)"),
        "virtio": tr("VirtIO-GPU"),
        "vmware": tr("VMware"),
        "cirrus": tr("Cirrus"),
        "serial0": tr("Serial port"),
        "qxl2": tr("QXL (dual)"),
        "qxl3": tr("QXL (triple)"),
        "qxl4": tr("QXL (quad)"),
    },
    "scsihw": {
        "lsi": tr("LSI 53C895A"),
        "lsi53c810": tr("LSI 53C810"),
        "megasas": tr("MegaSAS"),
        "pvscsi": tr("VMware PVSCSI"),
        "virtio-scsi-single": tr("VirtIO SCSI Single"),
        "virtio-scsi-pci": tr("VirtIO SCSI PCI"),
    },
    "ostype": {
        "other": tr("Not set"),
        "wxp": tr("Windows XP"),
        "w2k": tr("Windows 2000"),
        "w2k3": tr("Windows 2003"),
        "w2k8": tr("Windows 2008"),
        "w2k12": tr("Windows 2012"),
        "wvista": tr("Windows Vista"),
        "win7": tr("Windows 7"),
        "win8": tr("Windows 8"),
        "win10": tr("Windows 10/11"),
        "l24": tr("Linux 2.4"),
        "l26": tr("Linux 2.6+"),
        "solaris": tr("Solaris"),
    },
    "rtc": {
        "utc": tr("UTC"),
        "localtime": tr("Local"),
    },
    "keyboard": {
        "ar": tr("Arabic"),
        "da": tr("Danish"),
        "de": tr("German"),
        "de-ch": tr("Swiss (German)"),
        "en-gb": tr("English (UK)"),
        "en-us": tr("English (US)"),
        "es": tr("Spanish"),
        "fi": tr("Finnish"),
        "fr": tr("French"),
        "fr-be": tr("French (Belgium)"),
        "fr-ca": tr("French (Canada)"),
        "fr-ch": tr("Swiss (French)"),
        "hr": tr("Croatian"),
        "hu": tr("Hungarian"),
        "is": tr("Icelandic"),
        "it": tr("Italian"),
        "ja": tr("Japanese"),
        "lt": tr("Lithuanian"),
        "mk": tr("Macedonian"),
        "nl": tr("Dutch"),
        "no": tr("Norwegian"),
        "pl": tr("Polish"),
        "pt": tr("Portuguese"),
        "pt-br": tr("Portuguese (Brazil)"),
        "ru": tr("Russian"),
        "sk": tr("Slovak"),
        "sl": tr("Slovenian"),
        "sv": tr("Swedish"),
        "tr": tr("Turkish"),
        "ua": tr("Ukrainian"),
    },
    "hotplug": {
        "0": tr("Disabled"),
        "1": tr("All"),
        "network": tr("Network"),
        "disk": tr("Disks"),
        "usb": tr("USB"),
        "network,disk": tr("Network, Disks"),
        "network,usb": tr("Network, USB"),
        "disk,usb": tr("Disks, USB"),
        "network,disk,usb": tr("Network, Disks, USB"),
    },
})

# Device keys that can be edited as raw strings
_EDITABLE_DEVICE_PREFIXES = {"net", "ide", "sata", "scsi", "virtio", "efidisk", "tpmstate", "usb", "hostpci", "serial"}


def _key_prefix(key):
    return key.rstrip("0123456789")


def is_net_key(key):
    return _key_prefix(key) == "net"


def _is_cdrom_value(val):
    return "media=cdrom" in str(val or "")


def is_cdrom_key(key, value=None):
    if value is not None and _is_cdrom_value(value):
        if _key_prefix(key) in ("ide", "sata", "scsi"):
            return True
    if key == "ide2" and (value is None or _is_cdrom_value(value)):
        return True
    return False


def is_disk_key(key, value=None):
    pfx = _key_prefix(key)
    if pfx not in ("virtio", "scsi", "sata", "ide"):
        return pfx == "efidisk"
    if value is not None and _is_cdrom_value(value):
        return False
    return True


def is_tpm_key(key):
    return _key_prefix(key) == "tpmstate"


def is_usb_key(key):
    return _key_prefix(key) == "usb"


def is_pci_key(key):
    return _key_prefix(key) == "hostpci"


def is_serial_key(key):
    return _key_prefix(key) == "serial"


_SYSTEM_KEYS = frozenset({"name", "cpu", "cores", "sockets", "memory",
                          "bios", "machine", "vga", "scsihw"})


def is_removable_key(key, value=None):
    if key in _SYSTEM_KEYS:
        return False
    if is_net_key(key) or is_tpm_key(key) or is_usb_key(key) \
            or is_pci_key(key) or is_serial_key(key):
        return True
    if is_disk_key(key, value) or is_cdrom_key(key, value):
        return True
    return False


# PVE defaults for keys absent from config API (hardware tab)
HW_DEFAULTS = {
    "cores": 1,
    "sockets": 1,
    "memory": 512,
    "cpu": "kvm64",
    "bios": "seabios",
    "machine": "i440fx",
    "vga": "std",
    "scsihw": "lsi",
}

# PVE defaults for keys absent from config API (options tab)
OPT_DEFAULTS = {
    "ostype": "l26",
    "acpi": 1,
    "agent": 0,
    "spice": 0,
    "spice_enhancements": 0,
    "kvm": 1,
    "tablet": 1,
    "keyboard": "en-us",
    "boot": "order=ide2;ide0;scsi0;virtio0;net0",
    "onboot": 0,
    "numa": 0,
    "hotplug": "network,disk,usb",
    "freeze": 0,
    "localtime": 0,
    "protection": 0,
    "reboot": 1,
    "rtc": "utc",
    "tdf": 0,
    "template": 0,
    "smbios1": "type=1,uuid=auto",
    "vcpus": 0,
}

# Config keys not shown in either tab
SERVICE_KEYS = {
    "digest", "description", "meta",
    "hookscript", "parent", "template",
    "searchdomain", "hostname", "password", "sshkeys",
    "ciuser", "cipassword", "cicustom",
    "running-machine", "running-qemu", "vmgenid",
}

# Editor type and choices for each editable config key
# Types: bool, int, string, choice (with choices list), readonly
FIELD_TYPES = {
    "name": "string",
    "cpu": ("choice", [
        "kvm64", "host", "qemu64", "max",
        "x86-64-v2", "x86-64-v2-AES",
        "x86-64-v3", "x86-64-v3-AES",
        "x86-64-v4", "x86-64-v4-AES",
    ]),
    "cores": "int",
    "sockets": "int",
    "memory": "int",
    "bios": ("choice", ["seabios", "ovmf"]),
    "machine": ("choice", ["i440fx", "q35"]),
    "vga": ("choice", ["std", "qxl", "virtio", "vmware", "cirrus", "serial0", "qxl2", "qxl3", "qxl4"]),
    "scsihw": ("choice", ["lsi", "lsi53c810", "megasas", "pvscsi", "virtio-scsi-single", "virtio-scsi-pci"]),
    "ostype": ("choice", [
        "other", "wxp", "w2k", "w2k3", "w2k8", "w2k12",
        "wvista", "win7", "win8", "win10",
        "l24", "l26", "solaris",
    ]),
    "acpi": "bool",
    "agent": "bool",
    "spice": "bool",
    "spice_enhancements": "bool",
    "kvm": "bool",
    "tablet": "bool",
    "onboot": "bool",
    "numa": "bool",
    "freeze": "bool",
    "localtime": "bool",
    "protection": "bool",
    "reboot": "bool",
    "tdf": "bool",
    "boot": "string",
    "bootdisk": "string",
    "hotplug": ("choice", ["0", "1", "network", "disk", "usb", "network,disk", "network,usb", "disk,usb", "network,disk,usb"]),
    "startup": "string",
    "rtc": ("choice", ["utc", "localtime"]),
    "keyboard": ("choice", [
        "ar", "da", "de", "de-ch", "en-gb", "en-us",
        "es", "fi", "fr", "fr-be", "fr-ca", "fr-ch",
        "hr", "hu", "is", "it", "ja", "lt", "mk",
        "nl", "no", "pl", "pt", "pt-br", "ru",
        "sk", "sl", "sv", "tr", "ua",
    ]),
    "smbios1": "string",
    "tags": "string",
    "vcpus": "int",
    "args": "string",
}

# Ordered groups for options tab
_OPT_SECTIONS = [
    ("os",           ["ostype"]),
    ("boot",         ["boot", "bootdisk", "startup", "onboot"]),
    ("video",        ["vga", "spice", "spice_enhancements", "tablet", "keyboard"]),
    ("system",       ["acpi", "kvm", "numa", "tdf", "rtc", "localtime"]),
    ("hotplug",      ["hotplug", "vcpus"]),
    ("behaviour",    ["agent", "freeze", "protection", "reboot"]),
    ("misc",         ["tags", "smbios1", "args"]),
]

_HW_SECTIONS = [
    ("identity",       ["name"]),
    ("cpu",            ["cpu", "cores", "sockets"]),
    ("memory",         ["memory"]),
    ("system",         ["bios", "machine", "vga", "scsihw"]),
    ("network",        [f"net{i}" for i in range(32)]),
    ("storage",        [f"ide{i}" for i in range(4)] +
                        [f"sata{i}" for i in range(6)] +
                        [f"scsi{i}" for i in range(31)] +
                        [f"virtio{i}" for i in range(16)] +
                        ["efidisk0", "tpmstate0"]),
    ("usb",            [f"usb{i}" for i in range(5)]),
    ("pci",            [f"hostpci{i}" for i in range(16)]),
    ("serial",         [f"serial{i}" for i in range(4)]),
]

# Formatter helpers
# ---------------------------------------------------------------------------

def _fmt_memory(val):
    try:
        mb = int(val)
        if mb >= 1024:
            gb = mb / 1024
            if mb % 1024 == 0:
                return f"{mb // 1024} {tr('GB')}"
            return f"{gb:.1f} {tr('GB')} ({mb} {tr('MB')})"
        return f"{mb} {tr('MB')}"
    except (ValueError, TypeError):
        return str(val)


def _fmt_ostype(val):
    return {
        "other": tr("Not set"),
        "wxp": tr("Windows XP"),
        "w2k": tr("Windows 2000"),
        "w2k3": tr("Windows 2003"),
        "w2k8": tr("Windows 2008"),
        "w2k12": tr("Windows 2012"),
        "wvista": tr("Windows Vista"),
        "win7": tr("Windows 7"),
        "win8": tr("Windows 8"),
        "win10": tr("Windows 10/11"),
        "l24": tr("Linux 2.4"),
        "l26": tr("Linux 2.6+"),
        "solaris": tr("Solaris"),
    }.get(str(val), str(val))


def _fmt_bool(val):
    return tr("Yes") if val in (1, "1", True) else tr("No")


def _fmt_agent(val):
    return tr("Enabled") if val in (1, "1", True) else tr("Disabled")


def _fmt_boot(val):
    val = str(val)
    if val.startswith("order="):
        parts = val[6:].split(";")
        return tr("Boot order: ") + ", ".join(parts)
    if val == "cdn":
        return tr("CDN (network)")
    return val


def _fmt_hotplug(val):
    return {
        "network,disk,usb": tr("Network, Disks, USB"),
        "network,disk": tr("Network, Disks"),
        "network,usb": tr("Network, USB"),
        "disk,usb": tr("Disks, USB"),
        "network": tr("Network"),
        "disk": tr("Disks"),
        "usb": tr("USB"),
        "1": tr("All"),
        "0": tr("Disabled"),
    }.get(val, val)


def _fmt_startup(val):
    parts = str(val).split(",")
    out = []
    for p in parts:
        if p.startswith("order="):
            out.append(f"{tr('Order: ')}{p[6:]}")
        elif p.startswith("up="):
            out.append(f"{tr('Delay: ')}{p[3:]}{tr('s')}")
        elif p.startswith("down="):
            out.append(f"{tr('Shutdown: ')}{p[5:]}{tr('s')}")
    return " | ".join(out) if out else str(val)


def _fmt_keyboard(val):
    return {
        "ar": tr("Arabic"), "da": tr("Danish"), "de": tr("German"),
        "de-ch": tr("Swiss (German)"), "en-gb": tr("English (UK)"),
        "en-us": tr("English (US)"), "es": tr("Spanish"), "fi": tr("Finnish"),
        "fr": tr("French"), "fr-be": tr("French (Belgium)"),
        "fr-ca": tr("French (Canada)"), "fr-ch": tr("Swiss (French)"),
        "hr": tr("Croatian"), "hu": tr("Hungarian"), "is": tr("Icelandic"),
        "it": tr("Italian"), "ja": tr("Japanese"), "lt": tr("Lithuanian"),
        "mk": tr("Macedonian"), "nl": tr("Dutch"), "no": tr("Norwegian"),
        "pl": tr("Polish"), "pt": tr("Portuguese"),
        "pt-br": tr("Portuguese (Brazil)"), "ru": tr("Russian"),
        "sk": tr("Slovak"), "sl": tr("Slovenian"), "sv": tr("Swedish"),
        "tr": tr("Turkish"), "ua": tr("Ukrainian"),
    }.get(val, val)


def _fmt_cpu(val):
    val = str(val)
    if val.startswith("custom-"):
        return f"x86-64 {val[7:]} ({tr('PVE custom')})"
    return {
        "kvm64": tr("KVM64 (compatible)"),
        "host": tr("Host (maximum)"),
        "qemu64": tr("QEMU64"),
        "x86-64-v2": tr("x86-64 v2"),
        "x86-64-v2-AES": tr("x86-64 v2 + AES"),
        "x86-64-v3": tr("x86-64 v3"),
        "x86-64-v3-AES": tr("x86-64 v3 + AES"),
        "x86-64-v4": tr("x86-64 v4"),
        "x86-64-v4-AES": tr("x86-64 v4 + AES"),
        "max": tr("Host (max, risky)"),
    }.get(val, val)


def _fmt_scsihw(val):
    return {
        "lsi": tr("LSI 53C895A"),
        "lsi53c810": tr("LSI 53C810"),
        "megasas": tr("MegaSAS"),
        "pvscsi": tr("VMware PVSCSI"),
        "virtio-scsi-single": tr("VirtIO SCSI Single"),
        "virtio-scsi-pci": tr("VirtIO SCSI PCI"),
    }.get(val, val)


def _fmt_vga(val):
    return {
        "std": tr("VGA"),
        "qxl": tr("QXL (SPICE)"),
        "virtio": tr("VirtIO-GPU"),
        "vmware": tr("VMware"),
        "cirrus": tr("Cirrus"),
        "serial0": tr("Serial port"),
        "qxl2": tr("QXL (dual)"),
        "qxl3": tr("QXL (triple)"),
        "qxl4": tr("QXL (quad)"),
    }.get(val, val)


def _fmt_bios(val):
    return {"seabios": tr("SeaBIOS"), "ovmf": tr("OVMF (UEFI)")}.get(val, val)


def _fmt_machine(val):
    return {"i440fx": tr("i440fx"), "q35": tr("Q35")}.get(val, val) if val else val


def _fmt_rtc(val):
    return {"utc": tr("UTC"), "localtime": tr("Local")}.get(val, val)


def _fmt_smbios(val):
    parts = str(val).split(",")
    filtered = [p for p in parts if not p.startswith("uuid=")]
    return ", ".join(filtered) if filtered else tr("Set")


def _fmt_vcpus(val):
    return str(val) if val not in (0, "0") else tr("Not set")


def _fmt_net(val):
    """Parse a network device string: virtio=MAC,bridge=vmbr0,tag=10"""
    val = str(val)
    parts = val.split(",")
    first = parts[0]

    if "=" in first:
        model, mac = first.split("=", 1)
    else:
        model, mac = first, ""

    bridge = ""
    tag = ""
    for p in parts[1:]:
        if p.startswith("bridge="):
            bridge = p.split("=", 1)[1]
        elif p.startswith("tag="):
            tag = p.split("=", 1)[1]

    out = model
    if bridge:
        out += f" | {bridge}"
    if tag:
        out += f" | {tr('VLAN')} {tag}"
    if mac and mac != "none":
        out += f" | {mac}"
    return out


def _fmt_cdrom(val):
    """Format a cdrom value: volid,media=cdrom[,size=...] or /dev/cdrom,media=cdrom or none."""
    val = str(val or "").strip()
    if not val or val == "none":
        return tr("No media")
    if val == "/dev/cdrom,media=cdrom":
        return tr("Physical drive")
    parts = val.split(",")
    volid = parts[0]
    fname = volid.split("/")[-1] if "/" in volid else volid
    size = ""
    for p in parts[1:]:
        if p.startswith("size="):
            size = p.split("=", 1)[1]
    out = fname
    if size:
        out += f" | {size}"
    return out


def _fmt_disk(val):
    """Parse a disk string: storage:volume-name,size=32G,format=qcow2,cache=writeback,..."""
    val = str(val)
    parts = val.split(",")
    storage_part = parts[0]

    if ":" in storage_part:
        storage, volume = storage_part.split(":", 1)
    else:
        storage, volume = storage_part, ""

    fmt = ""
    cache = ""
    size = ""
    for p in parts[1:]:
        if p.startswith("cache="):
            cache = p.split("=", 1)[1]
        elif p.startswith("format="):
            fmt = p.split("=", 1)[1]
        elif p.startswith("size="):
            size = p.split("=", 1)[1]

    _cache_labels = {"none": tr("None"), "writeback": tr("Write back"),
                     "writethrough": tr("Write through"),
                     "directsync": tr("Direct sync"), "unsafe": tr("Unsafe")}
    cache = _cache_labels.get(cache, cache)

    out = storage
    if volume:
        out += f" | {volume}"
    if size:
        out += f" | {size}"
    if fmt:
        out += f" | {fmt}"
    if cache:
        out += f" | {tr('Cache: ')}{cache}"
    return out


def _fmt_usb(val):
    """Format USB device: host=1234:5678[,usb3=1] or spice."""
    val = str(val or "")
    if val == "spice":
        return tr("SPICE")
    parts = val.split(",")
    host = ""
    usb3 = False
    for p in parts:
        if p.startswith("host="):
            host = p.split("=", 1)[1]
        elif p == "usb3=1" or p == "usb3":
            usb3 = True
    out = host or tr("Unknown")
    if usb3:
        out += " | USB 3.0"
    return out


def _fmt_pci(val):
    """Format PCI device: 0000:01:02.0[,rombar=1][,x-vga=1]."""
    val = str(val or "")
    parts = val.split(",")
    host = parts[0] if parts else val
    rombar = False
    xvga = False
    for p in parts[1:]:
        if p.startswith("rombar=1"):
            rombar = True
        elif p.startswith("x-vga=1"):
            xvga = True
    out = host
    if rombar:
        out += f" | {tr('ROM')}"
    if xvga:
        out += f" | {tr('VGA passthrough')}"
    return out


def _fmt_serial(val):
    """Format serial port: socket or /dev/ttyS0."""
    val = str(val or "")
    if not val:
        return tr("Not set")
    if val == "socket":
        return tr("Socket")
    return val


# Formatter registry: key prefix -> callable(value) -> str
_FORMATTERS = {
    "memory": _fmt_memory,
    "ostype": _fmt_ostype,
    "acpi": _fmt_bool,
    "spice": _fmt_bool,
    "spice_enhancements": _fmt_bool,
    "kvm": _fmt_bool,
    "tablet": _fmt_bool,
    "onboot": _fmt_bool,
    "numa": _fmt_bool,
    "freeze": _fmt_bool,
    "localtime": _fmt_bool,
    "protection": _fmt_bool,
    "reboot": _fmt_bool,
    "tdf": _fmt_bool,
    "template": _fmt_bool,
    "agent": _fmt_agent,
    "boot": _fmt_boot,
    "hotplug": _fmt_hotplug,
    "startup": _fmt_startup,
    "rtc": _fmt_rtc,
    "keyboard": _fmt_keyboard,
    "cpu": _fmt_cpu,
    "scsihw": _fmt_scsihw,
    "vga": _fmt_vga,
    "bios": _fmt_bios,
    "machine": _fmt_machine,
    "smbios1": _fmt_smbios,
    "vcpus": _fmt_vcpus,
    "sockets": str,
    "cores": str,
}

# Disk and network device prefixes
_DISK_PREFIXES = {"ide", "sata", "scsi", "virtio", "efidisk", "tpmstate"}
_NET_PREFIXES = {"net"}
_USB_PREFIXES = {"usb"}
_PCI_PREFIXES = {"hostpci"}
_SERIAL_PREFIXES = {"serial"}


def format_value(key, value):
    if key in _FORMATTERS:
        return _FORMATTERS[key](value)
    prefix = key.rstrip("0123456789")
    if is_cdrom_key(key, value):
        return _fmt_cdrom(value)
    if prefix in _DISK_PREFIXES:
        return _fmt_disk(value)
    if prefix in _NET_PREFIXES:
        return _fmt_net(value)
    if prefix in _USB_PREFIXES:
        return _fmt_usb(value)
    if prefix in _PCI_PREFIXES:
        return _fmt_pci(value)
    if prefix in _SERIAL_PREFIXES:
        return _fmt_serial(value)
    return str(value)


def get_editor_spec(key):
    """Return (field_type, choices, display_labels) for a config key."""
    if key in FIELD_TYPES:
        spec = FIELD_TYPES[key]
        if isinstance(spec, tuple):
            ft, choices = spec[0], spec[1]
            labels = CHOICE_LABELS.get(key, {})
            return (ft, choices, labels)
        return (spec, None, None)
    prefix = key.rstrip("0123456789")
    if prefix in _EDITABLE_DEVICE_PREFIXES:
        return ("string", None, None)
    return ("readonly", None, None)


# Public API
# ---------------------------------------------------------------------------


_HW_SECTION_LABELS = tr_dict(lambda: {
    "identity": lambda: tr("Identity"),
    "cpu": lambda: tr("CPU"),
    "memory": lambda: tr("Memory"),
    "system": lambda: tr("System"),
    "network": lambda: tr("Network"),
    "storage": lambda: tr("Storage"),
    "usb": lambda: tr("USB"),
    "pci": lambda: tr("PCI"),
    "serial": lambda: tr("Serial ports"),
})

_OPT_SECTION_LABELS = tr_dict(lambda: {
    "os": lambda: tr("OS"),
    "boot": lambda: tr("Boot"),
    "video": lambda: tr("Display"),
    "system": lambda: tr("System"),
    "hotplug": lambda: tr("Hotplug"),
    "behaviour": lambda: tr("Behaviour"),
    "misc": lambda: tr("Misc"),
})


def get_hardware_rows(config_data, detail_data=None):
    config = dict(config_data) if config_data else {}
    for key, default in HW_DEFAULTS.items():
        if key not in config:
            config[key] = default
    rows = []
    for section_name, keys in _HW_SECTIONS:
        section_label = _HW_SECTION_LABELS.get(section_name, lambda: section_name)()
        section_rows = []
        for key in keys:
            if key in config:
                label = HW_LABELS.get(key) or _device_label(key, config[key])
                value = format_value(key, config[key])
                section_rows.append((key, label, value, section_name))
        if section_rows:
            rows.append(("__section__", section_label, "", section_name))
            rows.extend(section_rows)
    if detail_data:
        rm = detail_data.get("running-machine")
        if rm:
            label = HW_LABELS.get("running-machine", "running-machine")
            rows.append(("running-machine", label, rm, "system"))
    return rows


def get_options_rows(config_data):
    config = dict(config_data) if config_data else {}
    for key, default in OPT_DEFAULTS.items():
        if key not in config:
            config[key] = default
    hw_keys = set()
    for _section_name, keys in _HW_SECTIONS:
        for key in keys:
            hw_keys.add(key)
    opt_keys = set()
    for _section_name, keys in _OPT_SECTIONS:
        for key in keys:
            opt_keys.add(key)
    extra = set()
    for key in config:
        if key not in hw_keys and key not in SERVICE_KEYS and key not in opt_keys:
            extra.add(key)
    rows = []
    for section_name, keys in _OPT_SECTIONS:
        section_label = _OPT_SECTION_LABELS.get(section_name, lambda: section_name)()
        section_rows = []
        for key in keys:
            if key in config:
                label = HW_LABELS.get(key) or _device_label(key, config[key])
                formatted = format_value(key, config[key])
                section_rows.append((key, label, formatted, section_name))
        if section_rows:
            rows.append(("__section__", section_label, "", section_name))
            rows.extend(section_rows)
    if extra:
        rows.append(("__section__", _OPT_SECTION_LABELS.get("misc", lambda: tr("Misc"))(), "", "misc"))
        for key in sorted(extra):
            label = HW_LABELS.get(key) or _device_label(key, config[key])
            formatted = format_value(key, config[key])
            rows.append((key, label, formatted, "misc"))
    return rows
