import os

class DirectoryUtils:

    # The directory that you cloned the repo into. E.g. "/home/<USER>/<repo>".
    root_dir = None

    def __init__(self):
        self.root_dir = os.path.abspath(os.path.dirname(__file__) + '/..')
