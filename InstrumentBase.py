from abc import ABC, abstractmethod
import time

class InstrumentBase(ABC):
    """Abstract base class for instruments used by the GUI.

    Subclasses should implement low-level operations the server expects:
    - `open(address, timeout)`
    - `close()`
    - `write(cmd)` and `query(q)` for instrument I/O
    - `apply_smu(which, cfg)` (optional)
    - `measure()` returning a dict of measurements
    - `update(settings)` to accept generic per-device updates
    """

    DEFAULT_SETTINGS = {}
    def __init__(self):
        self.settings = self.DEFAULT_SETTINGS.copy()
        self.inst = None
        self.delay = 0.02
    def get(self, key):
        '''Get a setting from the current settings dict.'''
        return self.settings.get(key, self.DEFAULT_SETTINGS.get(key))
    @abstractmethod
    def open(self):
        raise NotImplementedError()
    def close(self):
        if self.inst is not None:
            try:
                self.inst.close()
            except Exception:
                pass
            self.inst = None
        else:
            raise RuntimeError('Cannot close instrument. Instrument is not open!')
    def write(self, cmd:str):
        if self.inst is None:
            raise RuntimeError('Instrument not open')
        self.inst.write(cmd)
        time.sleep(self.delay)
    def query(self, q:str, output_type=str):
        if self.inst is None:
            raise RuntimeError('instrument not open')
        res = output_type(self.inst.query(q).strip())
        time.sleep(self.delay)
        return res
    @abstractmethod
    def update(self, settings: dict):
        """Optional: accept a generic settings dict and apply them.

        This allows the server to send device-specific payloads
        (for example {'a': {...}, 'b': {...}} for a Keithley 2602).
        Implementations should return a dict or True/False.
        """
        raise NotImplementedError()
    @abstractmethod
    def card_html(self, iid: str) -> str:
        """Return an HTML string for the device card shown on /connect.

        Subclasses should produce a small block of HTML to be injected into
        the devices container. `iid` is the instrument id assigned by the
        server and `type_name` is an optional human-readable device type.
        """
        raise NotImplementedError()
