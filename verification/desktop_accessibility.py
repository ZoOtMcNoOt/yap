"""AT-SPI queries for installed Linux desktop checks."""

import time

import pyatspi
from gi.repository import GLib


def descendants(node):
    yield node
    for child in node:
        if child is not None:
            yield from descendants(child)


def wait_for(description, predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            for node in descendants(pyatspi.Registry.getDesktop(0)):
                if predicate(node):
                    return node
        except GLib.Error as error:
            # WebKit can retire an accessibility node while the page changes.
            if error.domain != "atspi_error":
                raise
        time.sleep(0.1)
    raise RuntimeError(f"Did not find {description}")


def has_text(node, value):
    try:
        return node.queryText().getText(0, -1) == value
    except NotImplementedError:
        return False
