import datetime as dt
import sys

TEST_FILE_DIR = "tests/test_files"

two_hours = dt.timedelta(hours=2)


def get_test_file(path):
    """
    Helper function to open and read test files.
    """
    filepath = f"{TEST_FILE_DIR}/{path}"
    if sys.version_info[0] < 3:
        # On python 2, this library operates on bytes.
        f = open(filepath, "r")
    else:
        # On python 3, it operates on unicode. We need to specify an encoding
        # for systems for which the preferred encoding isn't utf-8 (e.g windows)
        f = open(filepath, "r", encoding="utf-8")
    text = f.read()
    f.close()
    return text
