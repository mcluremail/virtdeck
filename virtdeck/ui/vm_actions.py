from .i18n import tr, tr_dict

VM_ACTION_BUTTON_LABELS = tr_dict(lambda: {
    "start": tr("Start"),
    "shutdown": tr("Shutdown"),
    "reboot": tr("Reboot"),
    "reset": tr("Reset"),
    "stop": tr("Stop"),
    "resume": tr("Resume"),
})

VM_ACTION_MESSAGE_LABELS = tr_dict(lambda: {
    "start": tr("Start"),
    "shutdown": tr("Shutdown"),
    "stop": tr("Force stop"),
    "reboot": tr("Reboot"),
    "reset": tr("Reset"),
    "resume": tr("Resume"),
})

VM_ACTION_ICONS = {
    "start": "start",
    "shutdown": "shutdown",
    "reboot": "reboot",
    "reset": "reset",
    "stop": "stop",
    "resume": "resume",
}

VM_ACTION_TOOLTIPS = tr_dict(lambda: {
    "start": tr("Start VM"),
    "shutdown": tr("Send ACPI shutdown signal to VM"),
    "reboot": tr("Send ACPI reboot signal to VM"),
    "reset": tr("Hard reset VM (unsaved data will be lost)"),
    "stop": tr("Force stop VM (kill process, unsaved data lost)"),
    "resume": tr("Resume suspended VM"),
})

VM_EXTRA_ACTION_LABELS = tr_dict(lambda: {
    "clone": tr("Clone"),
    "convert_template": tr("Convert to Template"),
    "convert_vm": tr("Convert to VM"),
})

VM_EXTRA_ACTION_ICONS = {
    "clone": "clone",
    "convert_template": "template",
    "convert_vm": "vm",
}

VM_EXTRA_ACTION_TOOLTIPS = tr_dict(lambda: {
    "clone": tr("Clone this VM"),
    "convert_template": tr("Convert this VM to a template (VM must be stopped)"),
    "convert_vm": tr("Convert this template back to a VM"),
})

_CONFIRM_ACTIONS = ("stop", "reset", "shutdown", "reboot")

_CONFIRM_MESSAGES = {
    "stop": "Force stop VM {vmid}? Unsaved data will be lost.",
    "reset": "Force reset VM {vmid}?",
    "shutdown": "Send ACPI shutdown to VM {vmid}?",
    "reboot": "Send ACPI reboot to VM {vmid}?",
}


def confirm_vm_action(action, vmid, parent=None):
    """Show confirmation dialog for destructive VM actions.
    Returns True if user confirmed, False if cancelled or action doesn't need confirmation.
    """
    if action not in _CONFIRM_ACTIONS:
        return True
    from PySide6.QtWidgets import QMessageBox
    msg_text = tr(_CONFIRM_MESSAGES[action]).format(vmid=vmid)
    msg = QMessageBox(QMessageBox.Warning, tr("Confirm"), msg_text, parent=parent)
    yes = msg.addButton(tr("Yes"), QMessageBox.YesRole)
    msg.addButton(tr("No"), QMessageBox.NoRole)
    msg.setDefaultButton(yes)
    msg.exec()
    return msg.clickedButton() == yes


def confirm_snapshot_delete(snap_name, parent=None):
    """Show confirmation dialog for snapshot deletion."""
    from PySide6.QtWidgets import QMessageBox
    msg_text = tr("Delete snapshot \"{name}\"?").format(name=snap_name)
    msg = QMessageBox(QMessageBox.Warning, tr("Confirm"), msg_text, parent=parent)
    yes = msg.addButton(tr("Yes"), QMessageBox.YesRole)
    msg.addButton(tr("No"), QMessageBox.NoRole)
    msg.setDefaultButton(yes)
    msg.exec()
    return msg.clickedButton() == yes


def confirm_snapshot_rollback(snap_name, parent=None):
    """Show confirmation dialog for snapshot rollback."""
    from PySide6.QtWidgets import QMessageBox
    msg_text = tr("Roll back to snapshot \"{name}\"?").format(name=snap_name)
    info_text = tr("The VM will be reverted to the state saved in this snapshot.")
    msg = QMessageBox(QMessageBox.Warning, tr("Confirm"), msg_text, parent=parent)
    msg.setInformativeText(info_text)
    yes = msg.addButton(tr("Yes"), QMessageBox.YesRole)
    msg.addButton(tr("No"), QMessageBox.NoRole)
    msg.setDefaultButton(yes)
    msg.exec()
    return msg.clickedButton() == yes
