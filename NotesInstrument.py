from InstrumentBase import InstrumentBase


class NotesInstrument(InstrumentBase):
    """Non-hardware instrument used to store freeform notes with runs."""
    DEFAULT_SETTINGS = {}

    def __init__(self):
        super().__init__()
        self.text = ""
    def open(self, *args, **kwargs):
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
    def next(self)->dict:
        return {'text':self.text}
    def card_html(self, iid: str, type_name: str = 'notes') -> str:
        return f"""
            <h3>{type_name} <small>({iid})</small></h3>
            <button class=\"remove\">Remove</button>
            <div class=\"grid\">
                <label>Text:</label>
                <textarea data-key=\"text\" rows=\"4\" style=\"width:100%\">{self.text}</textarea>
            </div>
            """
