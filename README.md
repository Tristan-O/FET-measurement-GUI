Flask + pyvisa Keithley 2602 demo

Quick start

1. (Optional) Set the instrument address in the `KEITHLEY_ADDRESS` environment variable. Examples:

- `GPIB0::26::INSTR`
- `TCPIP0::192.168.1.100::inst0::INSTR`

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run the app:

```powershell
python main.py
```

4. Open a browser to `http://localhost:5000` — the page will show the connection status ("opened" when a Keithley 2602 is found).

Notes

- If `KEITHLEY_ADDRESS` is not set, the app will scan available VISA resources and query `*IDN?` to find a device that reports "2602" in its ID string.
- You need an appropriate VISA backend (NI-VISA or pyvisa-py) installed and configured on your machine.
