from optparse import OptionParser

from vobject.helper import deprecated

from .base import Component, new_from_behavior, readOne

"""
Compare VTODOs and VEVENTs in two iCalendar sources.
"""

version = "0.1"


def getSortKey(component):
    def getUID():
        return component.getChildValue("uid", "")

    # it's not quite as simple as getUID, need to account for recurrenceID and
    # sequence

    def getSequence():
        sequence = component.getChildValue("sequence", 0)
        return f"{int(sequence):05d}"

    def getRecurrenceID() -> str:
        recurrence_id = component.getChildValue("recurrence_id", None)
        return recurrence_id.isoformat() if recurrence_id else "0000-00-00"

    return getUID() + getSequence() + getRecurrenceID()


def sortByUID(components):
    return sorted(components, key=getSortKey)


def deleteExtraneous(component, ignore_dtstamp=False):
    """
    Recursively walk the component's children, deleting extraneous details like
    X-VOBJ-ORIGINAL-TZID.
    """
    for comp in component.components():
        deleteExtraneous(comp, ignore_dtstamp)
    for line in component.lines():
        if "X-VOBJ-ORIGINAL-TZID" in line.params:
            del line.params["X-VOBJ-ORIGINAL-TZID"]
    if ignore_dtstamp and hasattr(component, "dtstamp_list"):
        del component.dtstamp_list


def diff(left, right):
    """
    Take two VCALENDAR components, compare VEVENTs and VTODOs in them,
    return a list of object pairs containing just UID and the bits
    that didn't match, using None for objects that weren't present in one
    version or the other.

    When there are multiple ContentLines in one VEVENT, for instance many
    DESCRIPTION lines, such lines original order is assumed to be
    meaningful.  Order is also preserved when comparing (the unlikely case
    of) multiple parameters of the same type in a ContentLine

    """

    def processComponentLists(leftList, rightList):
        output = []
        rightIndex = 0
        rightListSize = len(rightList)

        for comp in leftList:
            if rightIndex >= rightListSize:
                output.append((comp, None))
            else:
                leftKey = getSortKey(comp)
                rightComp = rightList[rightIndex]
                rightKey = getSortKey(rightComp)
                while leftKey > rightKey:
                    output.append((None, rightComp))
                    rightIndex += 1
                    if rightIndex >= rightListSize:
                        output.append((comp, None))
                        break
                    else:
                        rightComp = rightList[rightIndex]
                        rightKey = getSortKey(rightComp)

                if leftKey < rightKey:
                    output.append((comp, None))
                elif leftKey == rightKey:
                    rightIndex += 1
                    matchResult = processComponentPair(comp, rightComp)
                    if matchResult is not None:
                        output.append(matchResult)

        return output

    def processComponentPair(leftComp, rightComp):
        """
        Return None if a match, or a pair of components including UIDs and
        any differing children.

        """
        leftChildKeys = leftComp.contents.keys()
        rightChildKeys = rightComp.contents.keys()

        differentContentLines = []
        differentComponents = {}

        for key in leftChildKeys:
            rightList = rightComp.contents.get(key, [])
            if isinstance(leftComp.contents[key][0], Component):
                compDifference = processComponentLists(leftComp.contents[key], rightList)
                if len(compDifference) > 0:
                    differentComponents[key] = compDifference

            elif leftComp.contents[key] != rightList:
                differentContentLines.append((leftComp.contents[key], rightList))

        for key in rightChildKeys:
            if key not in leftChildKeys:
                if isinstance(rightComp.contents[key][0], Component):
                    differentComponents[key] = ([], rightComp.contents[key])
                else:
                    differentContentLines.append(([], rightComp.contents[key]))

        if not differentContentLines and not differentComponents:
            return None

        _left = new_from_behavior(leftComp.name)
        _right = new_from_behavior(leftComp.name)
        # add a UID, if one existed, despite the fact that they'll always be the same
        uid = leftComp.getChildValue("uid")
        if uid is not None:
            _left.add("uid").value = uid
            _right.add("uid").value = uid

        for name, childPairList in differentComponents.items():
            leftComponents, rightComponents = zip(*childPairList)
            if len(leftComponents) > 0:
                # filter out None
                _left.contents[name] = filter(None, leftComponents)
            if len(rightComponents) > 0:
                # filter out None
                _right.contents[name] = filter(None, rightComponents)

        for leftChildLine, rightChildLine in differentContentLines:
            nonEmpty = leftChildLine or rightChildLine
            name = nonEmpty[0].name
            if leftChildLine is not None:
                _left.contents[name] = leftChildLine
            if rightChildLine is not None:
                _right.contents[name] = rightChildLine

        return _left, _right

    vevents = processComponentLists(
        sortByUID(getattr(left, "vevent_list", [])), sortByUID(getattr(right, "vevent_list", []))
    )

    vtodos = processComponentLists(
        sortByUID(getattr(left, "vtodo_list", [])), sortByUID(getattr(right, "vtodo_list", []))
    )

    return vevents + vtodos


@deprecated
def prettyDiff(leftObj, rightObj):
    return pretty_diff(leftObj, rightObj)


def pretty_diff(left_obj, right_obj):
    seperator_size = 15
    for left, right in diff(left_obj, right_obj):
        print("<" * seperator_size)
        if left is not None:
            left.pretty_print()
        print("=" * seperator_size)
        if right is not None:
            right.pretty_print()
        print(">" * seperator_size)


def main():
    options, args = getOptions()
    if args:
        ignore_dtstamp = options.ignore
        ics_file1, ics_file2 = args
        with open(ics_file1) as f, open(ics_file2) as g:
            cal1 = readOne(f)
            cal2 = readOne(g)
        deleteExtraneous(cal1, ignore_dtstamp=ignore_dtstamp)
        deleteExtraneous(cal2, ignore_dtstamp=ignore_dtstamp)
        prettyDiff(cal1, cal2)


def getOptions():
    # ----Configuration options---- #

    usage = "usage: %prog [options] ics_file1 ics_file2"
    parser = OptionParser(usage=usage, version=version)
    parser.set_description("ics_diff will print a comparison of two iCalendar files ")

    parser.add_option(
        "-i",
        "--ignore-dtstamp",
        dest="ignore",
        action="store_true",
        default=False,
        help="ignore DTSTAMP lines [default: False]",
    )

    (cmdline_options, args) = parser.parse_args()
    if len(args) < 2:
        print("error: too few arguments given")
        print(parser.format_help())
        return False, False

    return cmdline_options, args


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Aborted")
