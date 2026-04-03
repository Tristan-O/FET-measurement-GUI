from InstrumentBase import InstrumentBase


class NotesInstrument(InstrumentBase):
    """Non-hardware instrument used to store freeform notes with runs."""
    DEFAULT_SETTINGS = {}

    def __init__(self):
        super().__init__()
        self.idn = "NOTES"
        self.status = "open"
        self.text = ""
    def open(self, address=None, timeout=5):
        self.status = "open"
        return True
    def close(self):
        raise ValueError('Notes cannot be closed! Remove instead.')
    def update(self, settings: dict):
        settings = settings or {}
        if 'text' in settings:
            self.text = str(settings.get('text') or '')
        return True
    def start(self):
        return True
    def measure(self):
        return {'text':self.text}
    def next(self):
        return self.measure()
    def card_html(self, iid: str, type_name: str = 'notes') -> str:
        return f"""
            <h3>{type_name} <small>({iid})</small></h3>
            <p>Status: <span class=\"status\">{self.status}</span></p>
            <p>IDN: <span class=\"idn\">{self.idn}</span></p>
            <div class=\"device-controls\">\n      <button class=\"open\">Open</button>\n      <button class=\"close\">Close</button>\n      <button class=\"remove\">Remove</button>\n    </div>
            <div class=\"grid\">
            <div class=\"col\" id=\"{iid}-notes\">
                <h4>Notes</h4>
                <label>Text:</label>
                <textarea data-key=\"text\" rows=\"8\" style=\"width:100%\">{self.text}</textarea>
            </div>
            </div>
            """
