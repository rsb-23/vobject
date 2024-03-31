import datetime
import struct

from .helper import deprecated

try:
    # py3.9 and above
    import winreg as _winreg
except ImportError:
    # py3.7 and py3.8
    import _winreg  # noqa

handle = _winreg.ConnectRegistry(None, _winreg.HKEY_LOCAL_MACHINE)
tzparent = _winreg.OpenKey(handle, "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Time Zones")
parentsize = _winreg.QueryInfoKey(tzparent)[0]

localkey = _winreg.OpenKey(handle, "SYSTEM\\CurrentControlSet\\Control\\TimeZoneInformation")
WEEKS = datetime.timedelta(7)


def list_timezones():
    """Return a list of all time zones known to the system."""
    return [_winreg.EnumKey(tzparent, i) for i in range(parentsize)]


class Win32tz(datetime.tzinfo):
    """tzinfo class based on win32's timezones available in the registry.

    >>> local = Win32tz('Central Standard Time')
    >>> oct1 = datetime.datetime(month=10, year=2004, day=1, tzinfo=local)
    >>> dec1 = datetime.datetime(month=12, year=2004, day=1, tzinfo=local)
    >>> oct1.dst()
    datetime.timedelta(0, 3600)
    >>> dec1.dst()
    datetime.timedelta(0)
    >>> braz = Win32tz('E. South America Standard Time')
    >>> braz.dst(oct1)
    datetime.timedelta(0)
    >>> braz.dst(dec1)
    datetime.timedelta(0, 3600)
    """

    def __init__(self, name):
        self.data = Win32tzData(name)

    def utcoffset(self, dt):
        if self._isdst(dt):
            return datetime.timedelta(minutes=self.data.dstoffset)
        else:
            return datetime.timedelta(minutes=self.data.stdoffset)

    def dst(self, dt):
        if self._isdst(dt):
            minutes = self.data.dstoffset - self.data.stdoffset
            return datetime.timedelta(minutes=minutes)
        else:
            return datetime.timedelta(0)

    def tzname(self, dt):
        return self.data.dstname if self._isdst(dt) else self.data.stdname

    def _isdst(self, dt):
        dat = self.data
        dston = pick_nth_weekday(dt.year, dat.dstmonth, dat.dstdayofweek, dat.dsthour, dat.dstminute, dat.dstweeknumber)
        dstoff = pick_nth_weekday(
            dt.year, dat.stdmonth, dat.stddayofweek, dat.stdhour, dat.stdminute, dat.stdweeknumber
        )
        if dston < dstoff:
            return dston <= dt.replace(tzinfo=None) < dstoff
        else:
            return not (dstoff <= dt.replace(tzinfo=None) < dston)

    def __repr__(self):
        return "<win32tz - {0!s}>".format(self.data.display)


@deprecated
def pickNthWeekday(year, month, dayofweek, hour, minute, whichweek):
    return pick_nth_weekday(year, month, dayofweek, hour, minute, whichweek)


def pick_nth_weekday(year, month, dayofweek, hour, minute, whichweek):
    """dayofweek == 0 means Sunday, whichweek > 4 means last instance"""
    first = datetime.datetime(year=year, month=month, hour=hour, minute=minute, day=1)
    weekdayone = first.replace(day=((dayofweek - first.isoweekday()) % 7 + 1))
    for n in range(whichweek - 1, -1, -1):
        dt = weekdayone + n * WEEKS
        if dt.month == month:
            return dt


class Win32tzData(object):
    """Read a registry key for a timezone, expose its contents."""

    def __init__(self, path):
        """Load path, or if path is empty, load local time."""
        if path:
            keydict = values_to_dict(_winreg.OpenKey(tzparent, path))
            self.display = keydict["Display"]
            self.dstname = keydict["Dlt"]
            self.stdname = keydict["Std"]

            # see http://ww_winreg.jsiinc.com/SUBA/tip0300/rh0398.htm
            tup = struct.unpack("=3l16h", keydict["TZI"])
            self.stdoffset = -tup[0] - tup[1]  # Bias + StandardBias * -1
            self.dstoffset = self.stdoffset - tup[2]  # + DaylightBias * -1

            offset = 3
            self.stdmonth = tup[1 + offset]
            self.stddayofweek = tup[2 + offset]  # Sunday=0
            self.stdweeknumber = tup[3 + offset]  # Last = 5
            self.stdhour = tup[4 + offset]
            self.stdminute = tup[5 + offset]

            offset = 11
        else:
            keydict = values_to_dict(localkey)

            self.stdname = keydict["StandardName"]
            self.dstname = keydict["DaylightName"]

            sourcekey = _winreg.OpenKey(tzparent, self.stdname)
            self.display = values_to_dict(sourcekey)["Display"]

            self.stdoffset = -keydict["Bias"] - keydict["StandardBias"]
            self.dstoffset = self.stdoffset - keydict["DaylightBias"]

            # see http://ww_winreg.jsiinc.com/SUBA/tip0300/rh0398.htm
            tup = struct.unpack("=8h", keydict["StandardStart"])

            offset = 0
            self.stdmonth = tup[1 + offset]
            self.stddayofweek = tup[2 + offset]  # Sunday=0
            self.stdweeknumber = tup[3 + offset]  # Last = 5
            self.stdhour = tup[4 + offset]
            self.stdminute = tup[5 + offset]

            tup = struct.unpack("=8h", keydict["DaylightStart"])

        self.dstmonth = tup[1 + offset]
        self.dstdayofweek = tup[2 + offset]  # Sunday=0
        self.dstweeknumber = tup[3 + offset]  # Last = 5
        self.dsthour = tup[4 + offset]
        self.dstminute = tup[5 + offset]


@deprecated
def valuesToDict(key):
    return values_to_dict(key)


def values_to_dict(key):
    """Convert a registry key's values to a dictionary."""
    size = _winreg.QueryInfoKey(key)[1]
    return {_winreg.EnumValue(key, i)[0]: _winreg.EnumValue(key, i)[1] for i in range(size)}


def _test():
    import doctest

    import win32tz  # noqa

    doctest.testmod(win32tz, verbose=False)


# Aliases for the class
win32tz = Win32tz
win32tz_data = Win32tzData

if __name__ == "__main__":
    _test()
