"""
VObject Overview
================
    vobject parses vCard or vCalendar files, returning a tree of Python objects.
    It also provids an API to create vCard or vCalendar data structures which
    can then be serialized.

    Parsing existing streams
    ------------------------
    Streams containing one or many L{Component<base.Component>}s can be
    parsed using L{readComponents<base.readComponents>}.  As each Component
    is parsed, vobject will attempt to give it a L{Behavior<behavior.Behavior>}.
    If an appropriate Behavior is found, any base64, quoted-printable, or
    backslash escaped data will automatically be decoded.  Dates and datetimes
    will be transformed to datetime.date or datetime.datetime instances.
    Components containing recurrence information will have a special rruleset
    attribute (a dateutil.rrule.rruleset instance).

    Validation
    ----------
    L{Behavior<behavior.Behavior>} classes implement validation for
    L{Component<base.Component>}s.  To validate, an object must have all
    required children.  There (TODO: will be) a toggle to raise an exception or
    just log unrecognized, non-experimental children and parameters.

    Creating objects programatically
    --------------------------------
    A L{Component<base.Component>} can be created from scratch.  No encoding
    is necessary, serialization will encode data automatically.  Factory
    functions (TODO: will be) available to create standard objects.

    Serializing objects
    -------------------
    Serialization:
      - Looks for missing required children that can be automatically generated,
        like a UID or a PRODID, and adds them
      - Encodes all values that can be automatically encoded
      - Checks to make sure the object is valid (unless this behavior is
        explicitly disabled)
      - Appends the serialized object to a buffer, or fills a new
        buffer and returns it

    Examples
    --------
    ==> moved to test_from_doctest.py > VobjectDoctest

"""

from . import icalendar, vcard
from .base import new_from_behavior, readComponents, readOne


def iCalendar():
    return new_from_behavior("vcalendar", "2.0")


def vCard():
    return new_from_behavior("vcard", "3.0")
