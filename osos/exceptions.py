class AnalysisException(Exception):
    pass


class OsosValueError(Exception):
    def __init__(self, error_class=None, message_parameters=None):
        pass


class OsosTypeError(Exception):
    def __init__(self, error_class=None, message_parameters=None):
        pass
