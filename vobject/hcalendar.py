r"""
hCalendar: A microformat for serializing iCalendar data
          (http://microformats.org/wiki/hcalendar)

Here is a sample event in an iCalendar:

BEGIN:VCALENDAR
PRODID:-//XYZproduct//EN
VERSION:2.0
BEGIN:VEVENT
URL:http://www.web2con.com/
DTSTART:20051005
DTEND:20051008
SUMMARY:Web 2.0 Conference
LOCATION:Argent Hotel\, San Francisco\, CA
END:VEVENT
END:VCALENDAR

and an equivalent event in hCalendar format with various elements optimized appropriately.

<span class="vevent">
 <a class="url" href="http://www.web2con.com/">
  <span class="summary">Web 2.0 Conference</span>:
  <abbr class="dtstart" title="2005-10-05">October 5</abbr>-
  <abbr class="dtend" title="2005-10-08">7</abbr>,
 at the <span class="location">Argent Hotel, San Francisco, CA</span>
 </a>
</span>
"""

from datetime import date, datetime, timedelta

import six

from .base import register_behavior
from .helper import CRLF, indent_str
from .icalendar import VCalendar2_0


class HCalendar(VCalendar2_0):
    name = "HCALENDAR"

    @classmethod
    def serialize(cls, obj, buf=None, lineLength=None, validate=True, *args, **kwargs):
        """
        Serialize iCalendar to HTML using the hCalendar microformat (http://microformats.org/wiki/hcalendar)
        """
        print("unused vars", lineLength, validate)  # todo: check and remove

        outbuf = buf or six.StringIO()
        level, tabwidth = 0, 3  # holds current indentation level

        def indent():
            return indent_str(level=level, tabwidth=tabwidth)

        def out(s):
            outbuf.write(indent())
            outbuf.write(s)

        # not serializing optional vcalendar wrapper

        vevents = obj.vevent_list

        for event in vevents:
            out(f'<span class="vevent">{CRLF}')
            level += 1

            # URL
            url = event.getChildValue("url")
            if url:
                out(f'<a class="url" href="{url}">{CRLF}')
                level += 1
            # SUMMARY
            summary = event.getChildValue("summary")
            if summary:
                out(f'<span class="summary">{summary}</span>:{CRLF}')

            # DTSTART
            dtstart = event.getChildValue("dtstart")
            if dtstart:
                machine = timeformat = ""
                if type(dtstart) is date:
                    timeformat = "%A, %B %e"
                    machine = "%Y%m%d"
                elif type(dtstart) is datetime:
                    timeformat = "%A, %B %e, %H:%M"
                    machine = "%Y%m%dT%H%M%S%z"

                # TODO: Handle non-datetime formats?
                # TODO: Spec says we should handle when dtstart isn't included

                out(
                    '<abbr class="dtstart", title="{0!s}">{1!s}</abbr>\r\n'.format(
                        dtstart.strftime(machine), dtstart.strftime(timeformat)
                    )
                )

                # DTEND
                dtend = event.getChildValue("dtend")
                if not dtend:
                    duration = event.getChildValue("duration")
                    if duration:
                        dtend = duration + dtstart
                # TODO: If lacking dtend & duration?

                if dtend:
                    human = dtend
                    # TODO: Human readable part could be smarter, excluding repeated data
                    if type(dtend) is date:
                        human = dtend - timedelta(days=1)

                    out(
                        '- <abbr class="dtend", title="{0!s}">{1!s}</abbr>\r\n'.format(
                            dtend.strftime(machine), human.strftime(timeformat)
                        )
                    )

            # LOCATION
            location = event.getChildValue("location")
            if location:
                out(f'at <span class="location">{location}</span>{CRLF}')

            description = event.getChildValue("description")
            if description:
                out(f'<div class="description">{description}</div>{CRLF}')

            if url:
                level -= 1
                out(f"</a>{CRLF}")

            level -= 1
            out(f"</span>{CRLF}")  # close vevent

        return buf or outbuf.getvalue()


register_behavior(HCalendar)
