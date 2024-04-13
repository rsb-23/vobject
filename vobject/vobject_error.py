class VObjectError(Exception):
    def __init__(self, msg, lineNumber=None):
        self.msg = msg
        if lineNumber is not None:
            self.lineNumber = lineNumber

    def __str__(self):
        if hasattr(self, "lineNumber"):
            return f"At line {self.lineNumber!s}: {self.msg!s}"
        else:
            return repr(self.msg)


class ParseError(VObjectError):
    pass


class ValidateError(VObjectError):
    pass


class NativeError(VObjectError):
    pass
