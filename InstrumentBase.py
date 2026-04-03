from abc import ABC, abstractmethod
import time
import threading
import queue as pyqueue
try:
    import pyvisa
    pyvisa_resource_manager = pyvisa.ResourceManager()
except Exception:
    pyvisa_resource_manager = None


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
        self.status = 'closed'
    def get(self, key):
        '''Get a setting from the current settings dict.'''
        return self.settings.get(key, self.DEFAULT_SETTINGS.get(key))
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
        self.status = 'closed'
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


class PyVisaInstrument(InstrumentBase):
    _ADDRESSES_IN_USE:set[str] = set()
    _io_queue = pyqueue.Queue()
    _io_thread = None
    _io_stop = threading.Event()
    def __init__(self):
        super().__init__()
        self.idn = '-'
        self.inst:None|pyvisa.Resource
    def _start_io_worker(self):
        if self._io_thread is not None and self._io_thread.is_alive():
            return
        self._io_stop.clear()
        PyVisaInstrument._io_thread = threading.Thread(target=self._io_worker, daemon=True)
        self._io_thread.start()
    def _stop_io_worker(self): 
        if self._io_thread is None:
            return
        self._io_stop.set()
        self._io_queue.put(None)
        self._io_thread.join(timeout=5)
        PyVisaInstrument._io_thread = None
    @staticmethod
    def _io_worker():
        while not PyVisaInstrument._io_stop.is_set():
            item = PyVisaInstrument._io_queue.get()
            if item is None:
                PyVisaInstrument._io_queue.task_done()
                break

            inst, op, cmd, box, done = item
            try:
                if inst is None:
                    raise RuntimeError('Instrument not open')

                if op == 'write':
                    inst.write(cmd)
                    box['result'] = None
                elif op == 'query':
                    raw = inst.query(cmd).strip()
                    box['result'] = raw
                else:
                    raise ValueError(f'Unknown queued op: {op}')
            except Exception as e:
                box['error'] = e
            finally:
                done.set()
                PyVisaInstrument._io_queue.task_done()
    def _enqueue_io(self, op: str, cmd: str):
        if self.inst is None:
            raise RuntimeError('Instrument not open')
        self._start_io_worker()
        box = {}
        done = threading.Event()
        self._io_queue.put((self.inst, op, cmd, box, done))
        done.wait()
        if 'error' in box:
            raise box['error']
        return box.get('result')
    def write(self, cmd:str, check_for_errors:bool=True):
        self._enqueue_io('write', cmd)
        if check_for_errors:
            self._check_for_errors(cmd)
    def query(self, q:str, output_type=str, check_for_errors:bool=True)->str|int|float:
        res = output_type(self._enqueue_io('query', q))
        if check_for_errors:
            self._check_for_errors(q)
        return res
    @abstractmethod
    def _check_for_errors(self, prev_cmd:str):
        raise NotImplementedError
        err = self.query(':SYST:ERR?')
        if 'no error' not in err.lower():
            print(f'{err} (from {prev_cmd})')
    @abstractmethod
    def _find(self, address:str=None, timeout:float=5, query='*IDN?', look_for:str='part of expected response of query to instrument'):
        if pyvisa_resource_manager is None:
            raise ValueError(f'Cannot find {self.__class__.__name__} because pyvisa is not installed!')
        if self.inst is not None:
            raise ValueError(f'This instrument has already been found as {self.inst.resource_name}!')

        resources = list(pyvisa_resource_manager.list_resources())
        try_order = []
        if address:
            try_order.append(address)
        try_order.extend(r for r in resources if r not in try_order and "GPIB" in r and r not in PyVisaInstrument._ADDRESSES_IN_USE) # prefer GPIB instruments
        try_order.extend(r for r in resources if r not in try_order and r not in PyVisaInstrument._ADDRESSES_IN_USE)

        for addr in try_order:
            try:
                inst = pyvisa_resource_manager.open_resource(addr, timeout=timeout * 1000) 
                idn = inst.query(query).strip()
                if look_for in idn:
                    self.inst = inst
                    self.status = 'open'
                    self.idn = idn
                    PyVisaInstrument._ADDRESSES_IN_USE.add(addr)
                    return True
                inst.close()
            except Exception as e:
                print(f"ERROR: While trying to open instrument at address {addr}, got exception", e)
        return False
    @abstractmethod
    def _initialize(self):
        raise NotImplementedError
        self.write('*CLS')
        self.write('*RST')
        self.update(self.settings)
    def open(self, address=None, timeout=5):
        if self.inst is None:
            self._find(address=address, timeout=timeout)
        return self._initialize()
    def close(self):
        if self.inst is None:
            self.status = 'closed'
            return

        self._stop_io_worker()

        addr = self.inst.resource_name
        res = super().close()
        PyVisaInstrument._ADDRESSES_IN_USE.discard(addr)
        return res
