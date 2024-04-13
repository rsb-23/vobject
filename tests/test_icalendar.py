import datetime as dt
import re
from unittest import TestCase

import dateutil
import pytz
from dateutil.rrule import MONTHLY, WEEKLY, rrule, rruleset
from dateutil.tz import tzutc

from vobject import base
from vobject.icalendar import (
    RecurringComponent,
    TimezoneComponent,
    VCalendar2_0,
    delta_to_offset,
    getTzid,
    parseDtstart,
    registerTzid,
    string_to_period,
    stringToTextValues,
    timedeltaToString,
    utc,
)

from .common import TEST_FILE_DIR, get_test_file, two_hours


class TestIcalendar(TestCase):
    """
    Tests for py
    """

    max_diff = None

    def test_parseDTStart(self):
        """
        Should take a content line and return a datetime object.
        """
        self.assertEqual(
            parseDtstart(base.textLineToContentLine("DTSTART:20060509T000000")), dt.datetime(2006, 5, 9, 0, 0)
        )

    def test_regexes(self):
        """
        Test regex patterns
        """
        self.assertEqual(re.findall(base.patterns["name"], "12foo-bar:yay"), ["12foo-bar", "yay"])
        self.assertEqual(re.findall(base.patterns["safe_char"], 'a;b"*,cd'), ["a", "b", "*", "c", "d"])
        self.assertEqual(re.findall(base.patterns["qsafe_char"], 'a;b"*,cd'), ["a", ";", "b", "*", ",", "c", "d"])
        self.assertEqual(
            re.findall(base.patterns["param_value"], '"quoted";not-quoted;start"after-illegal-quote', re.VERBOSE),
            ['"quoted"', "", "not-quoted", "", "start", "", "after-illegal-quote", ""],
        )
        match = base.line_re.match('TEST;ALTREP="http://www.wiz.org":value:;"')
        self.assertEqual(match.group("value"), 'value:;"')
        self.assertEqual(match.group("name"), "TEST")
        self.assertEqual(match.group("params"), ';ALTREP="http://www.wiz.org"')

    def test_stringToTextValues(self):
        """
        Test string lists
        """
        self.assertEqual(stringToTextValues(""), [""])
        self.assertEqual(stringToTextValues("abcd,efgh"), ["abcd", "efgh"])

    def test_stringToPeriod(self):
        """
        Test datetime strings
        """
        self.assertEqual(
            string_to_period("19970101T180000Z/19970102T070000Z"),
            (dt.datetime(1997, 1, 1, 18, 0, tzinfo=tzutc()), dt.datetime(1997, 1, 2, 7, 0, tzinfo=tzutc())),
        )
        self.assertEqual(
            string_to_period("19970101T180000Z/PT1H"),
            (dt.datetime(1997, 1, 1, 18, 0, tzinfo=tzutc()), dt.timedelta(0, 3600)),
        )

    def test_timedeltaToString(self):
        """
        Test timedelta strings
        """
        self.assertEqual(timedeltaToString(two_hours), "PT2H")
        self.assertEqual(timedeltaToString(dt.timedelta(minutes=20)), "PT20M")

    def test_delta_to_offset(self):
        """Test deltaToOffset() function."""

        # Sydney
        delta = dt.timedelta(hours=10)
        self.assertEqual(delta_to_offset(delta), "+1000")

        # New York
        delta = dt.timedelta(hours=-5)
        self.assertEqual(delta_to_offset(delta), "-0500")

        # Adelaide (see https://github.com/py-vobject/vobject/pull/12)
        delta = dt.timedelta(hours=9, minutes=30)
        self.assertEqual(delta_to_offset(delta), "+0930")

    def test_vtimezone_creation(self):
        """
        Test timezones
        """
        tzs = dateutil.tz.tzical(f"{TEST_FILE_DIR}/timezones.ics")
        pacific = TimezoneComponent(tzs.get("US/Pacific"))
        self.assertEqual(str(pacific), "<VTIMEZONE | <TZID{}US/Pacific>>")
        santiago = TimezoneComponent(tzs.get("Santiago"))
        self.assertEqual(str(santiago), "<VTIMEZONE | <TZID{}Santiago>>")
        for year in range(2001, 2010):
            for month in (2, 9):
                _dt = dt.datetime(year, month, 15, tzinfo=tzs.get("Santiago"))
                self.assertTrue(_dt.replace(tzinfo=tzs.get("Santiago")), _dt)

    @staticmethod
    def test_timezone_serializing():
        """
        Serializing with timezones test
        """
        tzs = dateutil.tz.tzical(f"{TEST_FILE_DIR}/timezones.ics")
        pacific = tzs.get("US/Pacific")
        cal = base.Component("VCALENDAR")
        cal.setBehavior(VCalendar2_0)
        ev = cal.add("vevent")
        ev.add("dtstart").value = dt.datetime(2005, 10, 12, 9, tzinfo=pacific)
        evruleset = rruleset()
        evruleset.rrule(rrule(WEEKLY, interval=2, byweekday=[2, 4], until=dt.datetime(2005, 12, 15, 9)))
        evruleset.rrule(rrule(MONTHLY, bymonthday=[-1, -5]))
        evruleset.exdate(dt.datetime(2005, 10, 14, 9, tzinfo=pacific))
        ev.rruleset = evruleset
        ev.add("duration").value = dt.timedelta(hours=1)

        apple = tzs.get("America/Montreal")
        ev.dtstart.value = dt.datetime(2005, 10, 12, 9, tzinfo=apple)

    def test_pytz_timezone_serializing(self):
        """
        Serializing with timezones from pytz test
        """

        # Avoid conflicting cached tzinfo from other tests
        def unregister_tzid(tzid):
            """Clear tzid from icalendar TZID registry"""
            if getTzid(tzid, False):
                registerTzid(tzid, None)

        unregister_tzid("US/Eastern")
        eastern = pytz.timezone("US/Eastern")
        cal = base.Component("VCALENDAR")
        cal.setBehavior(VCalendar2_0)
        ev = cal.add("vevent")
        ev.add("dtstart").value = eastern.localize(dt.datetime(2008, 10, 12, 9))
        serialized = cal.serialize()

        expected_vtimezone = get_test_file("tz_us_eastern.ics")
        self.assertIn(expected_vtimezone.replace("\r\n", "\n"), serialized.replace("\r\n", "\n"))

        # Exhaustively test all zones (just looking for no errors)

        for tzname in pytz.all_timezones:
            unregister_tzid(tzname)
            tz = TimezoneComponent(tzinfo=pytz.timezone(tzname))
            tz.serialize()

    @staticmethod
    def _add_tags(comp, uid, dtstamp, dtstart, dtend):  # todo: rename if required
        comp.add("uid").value = uid
        comp.add("dtstamp").value = dtstamp
        comp.add("dtstart").value = dtstart
        comp.add("dtend").value = dtend

    def test_freeBusy(self):
        """
        Test freebusy components
        """
        test_cal = get_test_file("freebusy.ics")

        vfb = base.new_from_behavior("VFREEBUSY")
        self._add_tags(
            vfb,
            uid="test",
            dtstamp=dt.datetime(2006, 2, 15, 0, tzinfo=utc),
            dtstart=dt.datetime(2006, 2, 16, 1, tzinfo=utc),
            dtend=None,
        )
        vfb.dtend.value = vfb.dtstart.value + two_hours
        vfb.add("freebusy").value = [(vfb.dtstart.value, two_hours / 2)]
        vfb.add("freebusy").value = [(vfb.dtstart.value, vfb.dtend.value)]

        self.assertEqual(vfb.serialize().replace("\r\n", "\n"), test_cal.replace("\r\n", "\n"))

    def test_availablity(self):
        """
        Test availability components
        """
        test_cal = get_test_file("availablity.ics")

        vcal = base.new_from_behavior("VAVAILABILITY")
        self._add_tags(
            vcal,
            uid="test",
            dtstamp=dt.datetime(2006, 2, 15, 0, tzinfo=utc),
            dtstart=dt.datetime(2006, 2, 16, 0, tzinfo=utc),
            dtend=dt.datetime(2006, 2, 17, 0, tzinfo=utc),
        )
        vcal.add("busytype").value = "BUSY"

        av = base.new_from_behavior("AVAILABLE")
        self._add_tags(
            av,
            uid="test1",
            dtstamp=dt.datetime(2006, 2, 15, 0, tzinfo=utc),
            dtstart=dt.datetime(2006, 2, 16, 9, tzinfo=utc),
            dtend=dt.datetime(2006, 2, 16, 12, tzinfo=utc),
        )
        av.add("summary").value = "Available in the morning"

        vcal.add(av)

        self.assertEqual(vcal.serialize().replace("\r\n", "\n"), test_cal.replace("\r\n", "\n"))

    def test_recurrence(self):
        """
        Ensure date valued UNTILs in rrules are in a reasonable timezone,
        and include that day (12/28 in this test)
        """
        test_file = get_test_file("recurrence.ics")
        cal = base.readOne(test_file)
        dates = list(cal.vevent.getrruleset())
        self.assertEqual(dates[0], dt.datetime(2006, 1, 26, 23, 0, tzinfo=tzutc()))
        self.assertEqual(dates[1], dt.datetime(2006, 2, 23, 23, 0, tzinfo=tzutc()))
        self.assertEqual(dates[-1], dt.datetime(2006, 12, 28, 23, 0, tzinfo=tzutc()))

    def test_recurring_component(self):
        """
        Test recurring events
        """
        vevent = RecurringComponent(name="VEVENT")

        # init
        self.assertTrue(vevent.isNative)

        # rruleset should be None at this point.
        # No rules have been passed or created.
        self.assertEqual(vevent.rruleset, None)

        # Now add start and rule for recurring event
        vevent.add("dtstart").value = dt.datetime(2005, 1, 19, 9)
        vevent.add("rrule").value = "FREQ=WEEKLY;COUNT=2;INTERVAL=2;BYDAY=TU,TH"
        self.assertEqual(list(vevent.rruleset), [dt.datetime(2005, 1, 20, 9, 0), dt.datetime(2005, 2, 1, 9, 0)])
        self.assertEqual(
            list(vevent.getrruleset(addRDate=True)),  # noqa # todo: check and remove noqa
            [dt.datetime(2005, 1, 19, 9, 0), dt.datetime(2005, 1, 20, 9, 0)],
        )

        # Also note that dateutil will expand all-day events (dt.date values)
        # to dt.datetime value with time 0 and no timezone.
        vevent.dtstart.value = dt.date(2005, 3, 18)
        self.assertEqual(list(vevent.rruleset), [dt.datetime(2005, 3, 29, 0, 0), dt.datetime(2005, 3, 31, 0, 0)])
        self.assertEqual(
            list(vevent.getrruleset(addRDate=True)),  # noqa # todo: check and remove noqa
            [dt.datetime(2005, 3, 18, 0, 0), dt.datetime(2005, 3, 29, 0, 0)],
        )

    def _recurrence_test(self, file_name):
        test_file = get_test_file(file_name)
        cal = base.readOne(test_file)
        dates = list(cal.vevent.getrruleset())
        self.assertEqual(dates[0], dt.datetime(2013, 1, 17, 0, 0))
        self.assertEqual(dates[1], dt.datetime(2013, 1, 24, 0, 0))
        self.assertEqual(dates[-1], dt.datetime(2013, 3, 28, 0, 0))

    def test_recurrence_without_tz(self):
        """
        Test recurring vevent missing any time zone definitions.
        """
        self._recurrence_test("recurrence-without-tz.ics")

    def test_recurrence_offset_naive(self):
        """
        Ensure recurring vevent missing some time zone definitions is parsing. See issue #75.
        """
        self._recurrence_test("recurrence-offset-naive.ics")
