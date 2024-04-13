"""vobject module for reading vCard and vCalendar files."""

from __future__ import annotations

import datetime as dt

from .helper import Character as Char
from .helper import byte_decoder, deprecated, get_buffer, indent_str, logger, split_by_size
from .helper.imports_ import TextIO, contextlib, copy, lru_cache, re, sys
from .vobject_error import NativeError, ParseError, VObjectError

logger.name = __name__


def to_unicode(value):
    """Converts a string argument to a unicode string.

    If the argument is already a unicode string, it is returned
    unchanged.  Otherwise it must be a byte string and is decoded as utf8.
    """
    return value if isinstance(value, str) else value.decode("utf-8")


def to_basestring(s):
    """Converts a string argument to a byte string.

    If the argument is already a byte string, it is returned unchanged.
    Otherwise it must be a unicode string and is encoded as utf8.
    """
    return s if isinstance(s, bytes) else s.encode("utf-8")


# --------------------------------- Main classes -------------------------------


class VBase:
    """
    Base class for ContentLine and Component.

    @ivar behavior:
        The Behavior class associated with this object, which controls
        validation, transformations, and encoding.
    @ivar parentBehavior:
        The object's parent's behavior, or None if no behaviored parent exists.
    @ivar isNative:
        Boolean describing whether this component is a Native instance.
    @ivar group:
        An optional group prefix, should be used only to indicate sort order in
        vCards, according to spec.

    Current spec: 4.0 (http://tools.ietf.org/html/rfc6350)
    """

    def __init__(self, group=None, *args, **kwds):
        super(VBase, self).__init__(*args, **kwds)
        self.name = None
        self.group = group
        self.behavior = None
        self.parentBehavior = None
        self.isNative = False

    def copy(self, copyit):
        self.group = copyit.group
        self.behavior = copyit.behavior
        self.parentBehavior = copyit.parentBehavior
        self.isNative = copyit.isNative

    def validate(self, *args, **kwds):
        """
        Call the behavior's validate method, or return True.
        """
        return self.behavior.validate(self, *args, **kwds) if self.behavior else True

    def getChildren(self):
        """
        Return an iterable containing the contents of the object.
        """
        return []

    def clearBehavior(self, cascade=True):
        """
        Set behavior to None. Do for all descendants if cascading.
        """
        self.behavior = None
        if cascade:
            self.transformChildrenFromNative()

    def autoBehavior(self, cascade=False):
        """
        Set behavior if name is in self.parentBehavior.knownChildren.

        If cascade is True, unset behavior and parentBehavior for all
        descendants, then recalculate behavior and parentBehavior.
        """
        parentBehavior = self.parentBehavior
        if parentBehavior is not None:
            knownChildTup = parentBehavior.knownChildren.get(self.name, None)
            if knownChildTup is not None:
                behavior = get_behavior(self.name, knownChildTup[2])
                if behavior is not None:
                    self.setBehavior(behavior, cascade)
                    if isinstance(self, ContentLine) and self.encoded:
                        self.behavior.decode(self)
            elif isinstance(self, ContentLine):
                self.behavior = parentBehavior.defaultBehavior
                if self.encoded and self.behavior:
                    self.behavior.decode(self)

    def setBehavior(self, behavior, cascade=True):
        """
        Set behavior. If cascade is True, autoBehavior all descendants.
        """
        self.behavior = behavior
        if cascade:
            for obj in self.getChildren():
                obj.parentBehavior = behavior
                obj.autoBehavior(True)

    def transformToNative(self):
        """
        Transform this object into a custom VBase subclass.

        transformToNative should always return a representation of this object.
        It may do so by modifying self in place then returning self, or by
        creating a new object.
        """
        if self.isNative or not self.behavior or not self.behavior.hasNative:
            return self
        self_orig = copy.copy(self)
        try:
            return self.behavior.transformToNative(self)
        except Exception as e:
            # wrap errors in transformation in a ParseError
            lineNumber = getattr(self, "lineNumber", None)

            if isinstance(e, ParseError):
                if lineNumber is not None:
                    e.lineNumber = lineNumber
                raise
            else:
                msg = "In transformToNative, unhandled exception on line {0}: {1}: {2}"
                msg = msg.format(lineNumber, sys.exc_info()[0], sys.exc_info()[1])
                msg = f"{msg} ({str(self_orig)})"
                raise ParseError(msg, lineNumber) from e

    def transformFromNative(self):
        """
        Return self transformed into a ContentLine or Component if needed.

        May have side effects.  If it does, transformFromNative and
        transformToNative MUST have perfectly inverse side effects. Allowing
        such side effects is convenient for objects whose transformations only
        change a few attributes.

        Note that it isn't always possible for transformFromNative to be a
        perfect inverse of transformToNative, in such cases transformFromNative
        should return a new object, not self after modifications.
        """
        if not (self.isNative and self.behavior and self.behavior.hasNative):
            return self
        try:
            return self.behavior.transformFromNative(self)
        except Exception as e:
            # wrap errors in transformation in a NativeError
            lineNumber = getattr(self, "lineNumber", None)
            if isinstance(e, NativeError):
                if lineNumber is not None:
                    e.lineNumber = lineNumber
                raise
            else:
                msg = "In transformFromNative, unhandled exception on line {0} {1}: {2}"
                msg = msg.format(lineNumber, sys.exc_info()[0], sys.exc_info()[1])
                raise NativeError(msg, lineNumber) from e

    def transformChildrenToNative(self):
        """
        Recursively replace children with their native representation.
        """
        pass

    def transformChildrenFromNative(self, clearBehavior=True):
        """
        Recursively transform native children to vanilla representations.
        """
        pass

    def serialize(self, buf=None, lineLength=75, validate=True, behavior=None, *args, **kwargs):
        """
        Serialize to buf if it exists, otherwise return a string.

        Use self.behavior.serialize if behavior exists.
        """
        if not behavior:
            behavior = self.behavior

        if behavior:
            logger.debug(f"serializing {self.name!s} with behavior {behavior!s}")
            return behavior.serialize(self, buf, lineLength, validate, *args, **kwargs)
        else:
            logger.debug(f"serializing {self.name!s} without behavior")
            return defaultSerialize(self, buf, lineLength)


@lru_cache(32)
def toVName(name, stripNum=0, upper=False):
    """
    Turn a Python name into an iCalendar style name,
    optionally uppercase and with characters stripped off.
    """
    if upper:
        name = name.upper()
    if stripNum != 0:
        name = name[:-stripNum]
    return name.replace("_", "-")


def to_vname(name: str, to_upper=False):
    """
    Turn a Python name into an iCalendar style name,
    optionally uppercase and with characters stripped off.
    """
    bad_suffix = "_list", "_param", "_paramlist"
    for suffix in bad_suffix:
        if name.endswith(suffix):
            name = name.rstrip(suffix)
            break
    if to_upper:
        name = name.upper()
    return name.replace("_", "-")


class ContentLine(VBase):
    """
    Holds one content line for formats like vCard and vCalendar.

    For example::
      <SUMMARY{u'param1' : [u'val1'], u'param2' : [u'val2']}Bastille Day Party>

    @ivar name:
        The uppercased name of the contentline.
    @ivar params:
        A dictionary of parameters and associated lists of values (the list may
        be empty for empty parameters).
    @ivar value:
        The value of the contentline.
    @ivar singletonparams:
        A list of parameters for which it's unclear if the string represents the
        parameter name or the parameter value. In vCard 2.1, "The value string
        can be specified alone in those cases where the value is unambiguous".
        This is crazy, but we have to deal with it.
    @ivar encoded:
        A boolean describing whether the data in the content line is encoded.
        Generally, text read from a serialized vCard or vCalendar should be
        considered encoded.  Data added programmatically should not be encoded.
    @ivar lineNumber:
        An optional line number associated with the contentline.
    """

    def __init__(self, name, params, value, group=None, encoded=False, isNative=False, lineNumber=None, *args, **kwds):
        """
        Take output from parseLine, convert params list to dictionary.

        Group is used as a positional argument to match parseLine's return
        """
        super(ContentLine, self).__init__(group, *args, **kwds)

        self.name = name.upper()
        self.encoded = encoded
        self.params = {}
        self.singletonparams = []
        self.isNative = isNative
        self.lineNumber = lineNumber
        self.value: str | dt.date = value

        def updateTable(x):
            if len(x) == 1:
                self.singletonparams += x
            else:
                paramlist = self.params.setdefault(x[0].upper(), [])
                paramlist.extend(x[1:])

        list(map(updateTable, params))

        qp = False
        if "ENCODING" in self.params and "QUOTED-PRINTABLE" in self.params["ENCODING"]:
            qp = True
            self.params["ENCODING"].remove("QUOTED-PRINTABLE")
            if len(self.params["ENCODING"]) == 0:
                del self.params["ENCODING"]
        if "QUOTED-PRINTABLE" in self.singletonparams:
            qp = True
            self.singletonparams.remove("QUOTED-PRINTABLE")
        if qp:
            if "ENCODING" in self.params:
                _encoding = self.params["ENCODING"]
            elif "CHARSET" in self.params:
                _encoding = self.params["CHARSET"][0]
            else:
                _encoding = "utf-8"
            self.value = byte_decoder(self.value, "quoted-printable").decode(_encoding)

    @classmethod
    def duplicate(cls, copyit):
        newcopy = cls("", {}, "")
        newcopy.copy(copyit)
        return newcopy

    def copy(self, copyit):
        super(ContentLine, self).copy(copyit)
        self.name = copyit.name
        self.value = copy.copy(copyit.value)
        self.encoded = self.encoded
        self.params = copy.copy(copyit.params)
        for k, v in self.params.items():
            self.params[k] = copy.copy(v)
        self.singletonparams = copy.copy(copyit.singletonparams)
        self.lineNumber = copyit.lineNumber

    def __eq__(self, other):
        return (self.name == other.name) and (self.params == other.params) and (self.value == other.value)

    def __getattr__(self, name):
        """
        Make params accessible via self.foo_param or self.foo_paramlist.

        Underscores, legal in python variable names, are converted to dashes,
        which are legal in IANA tokens.
        """
        try:
            if name.endswith("_param"):
                return self.params[toVName(name, 6, True)][0]
            elif name.endswith("_paramlist"):
                return self.params[toVName(name, 10, True)]
            else:
                raise AttributeError(name)
        except KeyError as e:
            raise AttributeError(name) from e

    def __setattr__(self, name, value):
        """
        Make params accessible via self.foo_param or self.foo_paramlist.

        Underscores, legal in python variable names, are converted to dashes,
        which are legal in IANA tokens.
        """
        if name.endswith("_param"):
            self.params[toVName(name, 6, True)] = value if type(value) is list else [value]
        elif name.endswith("_paramlist"):
            if type(value) is list:
                self.params[toVName(name, 10, True)] = value
            else:
                raise VObjectError("Parameter list set to a non-list")
        else:
            prop = getattr(self.__class__, name, None)
            if isinstance(prop, property):
                prop.fset(self, value)
            else:
                object.__setattr__(self, name, value)

    def __delattr__(self, name: str):
        try:
            if name.endswith("_param"):
                del self.params[toVName(name, 6, True)]
            elif name.endswith("_paramlist"):
                del self.params[toVName(name, 10, True)]
            else:
                object.__delattr__(self, name)
        except KeyError as e:
            raise AttributeError(name) from e

    def valueRepr(self):
        """
        Transform the representation of the value
        according to the behavior, if any.
        """
        return self.behavior.valueRepr(self) if self.behavior else self.value

    def __str__(self):
        try:
            return "<{0}{1}{2}>".format(self.name, self.params, self.valueRepr())
        except UnicodeEncodeError:
            return "<{0}{1}{2}>".format(self.name, self.params, self.valueRepr().encode("utf-8"))

    def __repr__(self):
        return str(self)

    def __unicode__(self):
        return f"<{self.name}{self.params}{self.valueRepr()}>"

    @deprecated
    def prettyPrint(self, level=0, tabwidth=3) -> None:
        self.pretty_print(level=level, tabwidth=tabwidth)

    def pretty_print(self, level=0, tabwidth=3) -> None:
        pre = indent_str(level=level, tabwidth=tabwidth)
        logger.info(pre, f"{pre} {self.name}: {self.valueRepr()}")
        if self.params:
            logger.info(pre, f"{pre} params for {self.name}:")
            pre1 = indent_str(level=level + 1, tabwidth=tabwidth)
            for k in self.params.keys():
                logger.info(f"{pre1} {k} {self.params[k]}")


class Component(VBase):
    """
    A complex property that can contain multiple ContentLines.

    For our purposes, a component must start with a BEGIN:xxxx line and end with
    END:xxxx, or have a PROFILE:xxx line if a top-level component.

    @ivar contents:
        A dictionary of lists of Component or ContentLine instances. The keys
        are the lowercased names of child ContentLines or Components.
        Note that BEGIN and END ContentLines are not included in contents.
    @ivar name:
        Uppercase string used to represent this Component, i.e VCARD if the
        serialized object starts with BEGIN:VCARD.
    @ivar useBegin:
        A boolean flag determining whether BEGIN: and END: lines should
        be serialized.
    """

    def __init__(self, name=None, *args, **kwds):
        super(Component, self).__init__(*args, **kwds)
        self.contents = {}
        if name:
            self.name = name.upper()
            self.useBegin = True
        else:
            self.name = ""
            self.useBegin = False

        self.autoBehavior()

    @classmethod
    def duplicate(cls, copyit):
        newcopy = cls()
        newcopy.copy(copyit)
        return newcopy

    def copy(self, copyit):
        super(Component, self).copy(copyit)

        # deep copy of contents
        self.contents = {}
        for key, lvalue in copyit.contents.items():
            newvalue = []
            for value in lvalue:
                newitem = value.duplicate(value)
                newvalue.append(newitem)
            self.contents[key] = newvalue

        self.name = copyit.name
        self.useBegin = copyit.useBegin

    def setProfile(self, name):
        """
        Assign a PROFILE to this unnamed component.

        Used by vCard, not by vCalendar.
        """
        if self.name or self.useBegin:
            if self.name == name:
                return
            raise VObjectError("This component already has a PROFILE or " "uses BEGIN.")
        self.name = name.upper()

    def __getattr__(self, name):
        """
        For convenience, make self.contents directly accessible.

        Underscores, legal in python variable names, are converted to dashes,
        which are legal in IANA tokens.
        """
        # if the object is being re-created by pickle, self.contents may not
        # be set, don't get into an infinite loop over the issue
        if name == "contents":
            return object.__getattribute__(self, name)
        try:
            if name.endswith("_list"):
                return self.contents[toVName(name, 5)]
            else:
                return self.contents[toVName(name)][0]
        except KeyError as e:
            raise AttributeError(name) from e

    normal_attributes = ["contents", "name", "behavior", "parentBehavior", "group"]

    def __setattr__(self, name, value):
        """
        For convenience, make self.contents directly accessible.

        Underscores, legal in python variable names, are converted to dashes,
        which are legal in IANA tokens.
        """
        if name not in self.normal_attributes and name.lower() == name:
            if type(value) is list:
                if name.endswith("_list"):
                    name = name[:-5]
                self.contents[toVName(name)] = value
            elif name.endswith("_list"):
                raise VObjectError("Component list set to a non-list")
            else:
                self.contents[toVName(name)] = [value]
        else:
            prop = getattr(self.__class__, name, None)
            if isinstance(prop, property):
                prop.fset(self, value)
            else:
                object.__setattr__(self, name, value)

    def __delattr__(self, name):
        try:
            if name not in self.normal_attributes and name.lower() == name:
                if name.endswith("_list"):
                    del self.contents[toVName(name, 5)]
                else:
                    del self.contents[toVName(name)]
            else:
                object.__delattr__(self, name)
        except KeyError as e:
            raise AttributeError(name) from e

    def getChildValue(self, childName, default=None, childNumber=0):
        """
        Return a child's value (the first, by default), or None.
        """
        child = self.contents.get(toVName(childName))
        return child[childNumber].value if child else default

    def add(self, objOrName, group=None):
        """
        Add objOrName to contents, set behavior if it can be inferred.

        If objOrName is a string, create an empty component or line based on
        behavior. If no behavior is found for the object, add a ContentLine.

        group is an optional prefix to the name of the object (see RFC 2425).
        """
        if isinstance(objOrName, VBase):
            obj = objOrName
            if self.behavior:
                obj.parentBehavior = self.behavior
                obj.autoBehavior(True)
        else:
            name = objOrName.upper()
            try:
                _id = self.behavior.knownChildren[name][2]
                behavior = get_behavior(name, _id)
                if behavior.isComponent:
                    obj = Component(name)
                else:
                    obj = ContentLine(name, [], "", group)
                obj.parentBehavior = self.behavior
                obj.behavior = behavior
                obj = obj.transformToNative()
            except (KeyError, AttributeError):
                obj = ContentLine(objOrName, [], "", group)

            if obj.behavior is None and self.behavior is not None and isinstance(obj, ContentLine):
                obj.behavior = self.behavior.defaultBehavior
        self.contents.setdefault(obj.name.lower(), []).append(obj)
        return obj

    def remove(self, obj):
        """
        Remove obj from contents.
        """
        named = self.contents.get(obj.name.lower())
        if named:
            with contextlib.suppress(ValueError):
                named.remove(obj)
                if len(named) == 0:
                    del self.contents[obj.name.lower()]

    def getChildren(self):
        """
        Return an iterable of all children.
        """
        for objList in self.contents.values():
            yield from objList

    def components(self):
        """
        Return an iterable of all Component children.
        """
        return (i for i in self.getChildren() if isinstance(i, Component))

    def lines(self):
        """
        Return an iterable of all ContentLine children.
        """
        return (i for i in self.getChildren() if isinstance(i, ContentLine))

    def sortChildKeys(self):
        try:
            first = [s for s in self.behavior.sortFirst if s in self.contents]
        except AttributeError:
            first = []
        return first + sorted(k for k in self.contents.keys() if k not in first)

    def getSortedChildren(self):
        return [obj for k in self.sortChildKeys() for obj in self.contents[k]]

    def setBehaviorFromVersionLine(self, versionLine):
        """
        Set behavior if one matches name, versionLine.value.
        """
        v = get_behavior(self.name, versionLine.value)
        if v:
            self.setBehavior(v)

    def transformChildrenToNative(self):
        """
        Recursively replace children with their native representation.

        Sort to get dependency order right, like vtimezone before vevent.
        """
        for childArray in (self.contents[k] for k in self.sortChildKeys()):
            for child in childArray:
                child = child.transformToNative()
                child.transformChildrenToNative()

    def transformChildrenFromNative(self, clearBehavior=True):
        """
        Recursively transform native children to vanilla representations.
        """
        for childArray in self.contents.values():
            for child in childArray:
                child = child.transformFromNative()
                child.transformChildrenFromNative(clearBehavior)
                if clearBehavior:
                    child.behavior = None
                    child.parentBehavior = None

    def __str__(self):
        if self.name:
            return f"<{self.name}| {self.getSortedChildren()}>"
        else:
            return f"<*unnamed*| {self.getSortedChildren()}>"

    def __repr__(self):
        return str(self)

    @deprecated
    def prettyPrint(self, level=0, tabwidth=3):
        self.pretty_print(level=level, tabwidth=tabwidth)

    def pretty_print(self, level=0, tabwidth=3):
        pre = indent_str(level=level, tabwidth=tabwidth)
        logger.info(f"{pre} {self.name}")
        if isinstance(self, Component):
            for line in self.getChildren():
                line.prettyPrint(level + 1, tabwidth)


# --------- Parsing functions and parseLine regular expressions ----------------


# Note that underscore is not legal for names, it's included because
# Lotus Notes uses it
patterns = {"name": "[a-zA-Z0-9_-]+", "safe_char": '[^";:,]', "qsafe_char": '[^"]'}
# the combined Python string replacement and regex syntax is a little confusing;
# remember that {foobar} is replaced with patterns['foobar'], so for instance
# param_value is any number of safe_chars or any number of qsaf_chars surrounded
# by double quotes.

patterns["param_value"] = ' "{qsafe_char!s} * " | {safe_char!s} * '.format(**patterns)

# get a tuple of two elements, one will be empty, the other will have the value
patterns["param_value_grouped"] = (
    """
" ( {qsafe_char!s} * )" | ( {safe_char!s} + )
""".format(
        **patterns
    )
)

# get a parameter and its values, without any saved groups
patterns["param"] = (
    r"""
; (?: {name!s} )                     # parameter name
(?:
    (?: = (?: {param_value!s} ) )?   # 0 or more parameter values, multiple
    (?: , (?: {param_value!s} ) )*   # parameters are comma separated
)*
""".format(
        **patterns
    )
)

# get a parameter, saving groups for name and value (value still needs parsing)
patterns["params_grouped"] = (
    r"""
; ( {name!s} )

(?: =
    (
        (?:   (?: {param_value!s} ) )?   # 0 or more parameter values, multiple
        (?: , (?: {param_value!s} ) )*   # parameters are comma separated
    )
)?
""".format(
        **patterns
    )
)

# get a full content line, break it up into group, name, parameters, and value
patterns["line"] = (
    r"""
^ ((?P<group> {name!s})\.)?(?P<name> {name!s}) # name group
  (?P<params> ;?(?: {param!s} )* )               # params group (may be empty)
: (?P<value> .* )$                             # value group
""".format(
        **patterns
    )
)

' "%(qsafe_char)s*" | %(safe_char)s* '  # what is this line?? - never assigned?

param_values_re = re.compile(patterns["param_value_grouped"], re.VERBOSE)
params_re = re.compile(patterns["params_grouped"], re.VERBOSE)
line_re = re.compile(patterns["line"], re.DOTALL | re.VERBOSE)
begin_re = re.compile("BEGIN", re.IGNORECASE)


def parseParams(string):
    """
    Parse parameters
    """
    _all = params_re.findall(string)
    allParameters = []
    for tup in _all:
        paramList = [tup[0]]  # tup looks like (name, valuesString)
        for pair in param_values_re.findall(tup[1]):
            # pair looks like ('', value) or (value, '')
            if pair[0] != "":
                paramList.append(pair[0])
            else:
                paramList.append(pair[1])
        allParameters.append(paramList)
    return allParameters


def parseLine(line, lineNumber=None):
    """
    Parse line
    """
    match = line_re.match(line)
    if match is None:
        raise ParseError(f"Failed to parse line: {line!s}", lineNumber)
    # Underscores are replaced with dash to work around Lotus Notes
    return (
        match.group("name").replace("_", "-"),
        parseParams(match.group("params")),
        match.group("value"),
        match.group("group"),
    )


# logical line regular expressions

patterns["lineend"] = r"(?:\r\n|\r|\n|$)"
patterns["wrap"] = r"{lineend!s} [\t ]".format(**patterns)
patterns["logicallines"] = (
    r"""
(
   (?: [^\r\n] | {wrap!s} )*
   {lineend!s}
)
""".format(
        **patterns
    )
)

patterns["wraporend"] = r"({wrap!s} | {lineend!s} )".format(**patterns)

wrap_re = re.compile(patterns["wraporend"], re.VERBOSE)
logical_lines_re = re.compile(patterns["logicallines"], re.VERBOSE)


@deprecated
def getLogicalLines(fp, allowQP=True):
    return get_logical_lines(fp, allow_qp=allowQP)


def get_logical_lines(fp, allow_qp=True):  # sourcery skip: low-code-quality
    """
    Iterate through a stream, yielding one logical line at a time.

    Because many applications still use vCard 2.1, we have to deal with the
    quoted-printable encoding for long lines, as well as the vCard 3.0 and
    vCalendar line folding technique, a whitespace character at the start
    of the line.

    Quoted-printable data will be decoded in the Behavior decoding phase.
    """
    # todo: simplify this logic
    if not allow_qp:
        val = fp.read(-1)

        lineNumber = 1
        for match in logical_lines_re.finditer(val):
            line, n = wrap_re.subn("", match.group())
            if line != "":
                yield line, lineNumber
            lineNumber += n

    else:
        quotedPrintable = False
        logicalLine = get_buffer()
        lineNumber = 0
        lineStartNumber = 0
        while True:
            line = fp.readline()
            if line == "":
                break
            line = line.rstrip(Char.CRLF)
            lineNumber += 1
            if line.rstrip() == "":
                if logicalLine.tell() > 0:
                    yield logicalLine.getvalue(), lineStartNumber
                lineStartNumber = lineNumber
                logicalLine = get_buffer()
                quotedPrintable = False
                continue

            if quotedPrintable and allow_qp:
                logicalLine.write("\n")
                logicalLine.write(line)
                quotedPrintable = False
            elif line[0] in Char.SPACEORTAB:
                logicalLine.write(line[1:])
            elif logicalLine.tell() > 0:
                yield logicalLine.getvalue(), lineStartNumber
                lineStartNumber = lineNumber
                logicalLine = get_buffer()
                logicalLine.write(line)
            else:
                logicalLine = get_buffer()
                logicalLine.write(line)

            # vCard 2.1 allows parameters to be encoded without a parameter name
            # False positives are unlikely, but possible.
            val = logicalLine.getvalue()
            if val[-1] == "=" and "quoted-printable" in val.lower():
                quotedPrintable = True

        if logicalLine.tell() > 0:
            yield logicalLine.getvalue(), lineStartNumber


def textLineToContentLine(text, n=None):
    return ContentLine(*parseLine(text, n), encoded=True, lineNumber=n)


def dquoteEscape(param):
    """
    Return param, or "param" if ',' or ';' or ':' is in param.
    """
    if '"' in param:
        raise VObjectError("Double quotes aren't allowed in parameter values.")
    for char in ",;:":  # sourcery skip # temp
        if char in param:
            return f'"{param}"'
    return param


@deprecated
def foldOneLine(outbuf, input_, lineLength=75):  # sourcery skip: extract-method
    """
    Folding line procedure that ensures multi-byte utf-8 sequences are not
    broken across lines

    TO-DO: This all seems odd. Is it still needed, especially in python3?
    """

    def outbuf_write(msg) -> None:
        try:
            outbuf.write(bytes(msg, "UTF-8"))
        except TypeError:
            # fall back on py2 syntax
            outbuf.write(msg)

    if len(input_) < lineLength:
        # Optimize for unfolded line case
        outbuf_write(input_)

    else:
        # Look for valid utf8 range and write that out
        start = 0  # sourcery skip: low-code-quality
        written = 0
        counter = 0  # counts line size in bytes
        decoded = to_unicode(input_)
        length = len(to_basestring(input_))
        while written < length:
            s = decoded[start]  # take one char
            size = len(to_basestring(s))  # calculate it's size in bytes
            if counter + size > lineLength:
                outbuf_write("\r\n ")
                counter = 1  # one for space

            outbuf_write(s)

            written += size
            counter += size
            start += 1

    outbuf_write("\r\n")


def fold_one_line(outbuf: TextIO, input_: str, line_length=75):
    """
    Folding line procedure that ensures multi-byte utf-8 sequences are not
    broken across lines
    """
    chunks = split_by_size(input_, byte_size=line_length)
    for chunk in chunks:
        outbuf.write(chunk)
    outbuf.write("\r\n")


def defaultSerialize(obj, buf, lineLength):
    """
    Encode and fold obj and its children, write to buf or return a string.
    """
    outbuf = buf or get_buffer()

    if isinstance(obj, Component):
        groupString = f"{obj.group}." if obj.group else ""
        if obj.useBegin:
            fold_one_line(outbuf, "{0}BEGIN:{1}".format(groupString, obj.name), lineLength)
        for child in obj.getSortedChildren():
            # validate is recursive, we only need to validate once
            child.serialize(outbuf, lineLength, validate=False)
        if obj.useBegin:
            fold_one_line(outbuf, "{0}END:{1}".format(groupString, obj.name), lineLength)

    elif isinstance(obj, ContentLine):
        startedEncoded = obj.encoded  # sourcery skip: extract-method
        if obj.behavior and not startedEncoded:
            obj.behavior.encode(obj)

        s = get_buffer()

        if obj.group is not None:
            s.write(f"{obj.group}.")
        s.write(obj.name.upper())
        keys = sorted(obj.params.keys())
        for key in keys:
            paramstr = ",".join(dquoteEscape(p) for p in obj.params[key])
            try:
                s.write(";{0}={1}".format(key, paramstr))
            except (UnicodeDecodeError, UnicodeEncodeError):
                s.write(";{0}={1}".format(key, paramstr.encode("utf-8")))
        try:
            s.write(":{0}".format(obj.value))
        except (UnicodeDecodeError, UnicodeEncodeError):
            s.write(":{0}".format(obj.value.encode("utf-8")))
        if obj.behavior and not startedEncoded:
            obj.behavior.decode(obj)
        fold_one_line(outbuf, s.getvalue(), lineLength)

    return buf or outbuf.getvalue()


class Stack:
    def __init__(self):
        self.stack = []

    def __len__(self):
        return len(self.stack)

    def top(self):
        return self.stack[-1] if self.stack else None

    def topName(self):
        return self.stack[-1].name if self.stack else None

    def modifyTop(self, item):
        top = self.top()
        if top:
            top.add(item)
        else:
            new = Component()
            self.push(new)
            new.add(item)  # add sets behavior for item and children

    def push(self, obj):
        self.stack.append(obj)

    def pop(self):
        return self.stack.pop()


def readComponents(streamOrString, validate=False, transform=True, ignoreUnreadable=False, allowQP=False):
    # sourcery skip: low-code-quality
    """
    Generate one Component at a time from a stream.
    """
    if isinstance(streamOrString, str):
        stream = get_buffer(streamOrString)
    else:
        stream = streamOrString

    try:
        stack = Stack()
        versionLine = None
        n = 0
        for line, n in get_logical_lines(stream, allowQP):
            if ignoreUnreadable:
                try:
                    vline = textLineToContentLine(line, n)
                except VObjectError as e:
                    if e.lineNumber is not None:
                        msg = "Skipped line {lineNumber}, message: {msg}"
                    else:
                        msg = "Skipped a line, message: {msg}"
                    logger.error(msg.format(lineNumber=e.lineNumber, msg=str(e)))
                    continue
            else:
                vline = textLineToContentLine(line, n)
            if vline.name == "VERSION":
                versionLine = vline
                stack.modifyTop(vline)
            elif vline.name == "BEGIN":
                stack.push(Component(vline.value, group=vline.group))
            elif vline.name == "PROFILE":
                if not stack.top():
                    stack.push(Component())
                stack.top().setProfile(vline.value)
            elif vline.name == "END":
                if len(stack) == 0:
                    err = "Attempted to end the {0} component but it was never opened"
                    raise ParseError(err.format(vline.value), n)

                if vline.value.upper() == stack.topName():  # START matches END
                    if len(stack) == 1:
                        component = stack.pop()
                        if versionLine is not None:
                            component.setBehaviorFromVersionLine(versionLine)
                        else:
                            behavior = get_behavior(component.name)
                            if behavior:
                                component.setBehavior(behavior)
                        if validate:
                            component.validate(raiseException=True)
                        if transform:
                            component.transformChildrenToNative()
                        yield component  # EXIT POINT
                    else:
                        stack.modifyTop(stack.pop())
                else:
                    err = "{0} component wasn't closed"
                    raise ParseError(err.format(stack.topName()), n)
            else:
                stack.modifyTop(vline)  # not a START or END line
        if stack.top():
            if stack.topName() is None:
                logger.warning("Top level component was never named")
            elif stack.top().useBegin:
                raise ParseError(f"Component {stack.topName()!s} was never closed", n)
            yield stack.pop()

    except ParseError as e:
        e.input = streamOrString
        raise


def readOne(stream, validate=False, transform=True, ignoreUnreadable=False, allowQP=False):
    """
    Return the first component from stream.
    """
    return next(readComponents(stream, validate, transform, ignoreUnreadable, allowQP))


# --------------------------- version registry ---------------------------------
__behaviorRegistry = {}


@deprecated
def registerBehavior(behavior, name=None, default=False, id=None):  # noqa D
    return register_behavior(behavior, name, default, _id=id)


def register_behavior(behavior, name=None, default=False, _id=None):
    """
    Register the given behavior.

    If default is True (or if this is the first version registered with this
    name), the version will be the default if no id is given.
    """
    if not name:
        name = behavior.name.upper()

    _id = _id or behavior.versionString
    if name in __behaviorRegistry:
        if default:
            __behaviorRegistry[name].insert(0, (id, behavior))
        else:
            __behaviorRegistry[name].append((id, behavior))
    else:
        __behaviorRegistry[name] = [(id, behavior)]


@deprecated
def getBehavior(name, id=None):  # noqa D
    return get_behavior(name, _id=id)


def get_behavior(name, _id=None):
    """
    Return a matching behavior if it exists, or None.

    If id is None, return the default for name.
    """
    name = name.upper()
    if name in __behaviorRegistry:
        if _id:
            for n, behavior in __behaviorRegistry[name]:
                if n == _id:
                    return behavior

        return __behaviorRegistry[name][0][1]
    return None


@deprecated
def newFromBehavior(name, id=None):  # noqa D
    return new_from_behavior(name=name, _id=id)


def new_from_behavior(name, _id=None):
    """
    Given a name, return a behaviored ContentLine or Component.
    """
    name = name.upper()
    behavior = get_behavior(name, _id)
    if behavior is None:
        raise VObjectError(f"No behavior found named {name!s}")
    obj = Component(name) if behavior.isComponent else ContentLine(name, [], "")
    obj.behavior = behavior
    obj.isNative = False
    return obj
