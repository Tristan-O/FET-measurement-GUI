import os
import threading
from flask import Flask, render_template_string

try:
	import pyvisa
except Exception:
	pyvisa = None

app = Flask(__name__)

# Shared state for instrument connection
class InstrumentState:
	def __init__(self):
		self.rm = None
		self.inst = None
		self.status = "not opened"
		self.idn = None

state = InstrumentState()

INDEX_HTML = """
<!doctype html>
<title>Keithley 2602 connection</title>
<h1>Keithley 2602 connection</h1>
<p><strong>Status:</strong> {{ status }}</p>
{% if idn %}<p><strong>IDN:</strong> {{ idn }}</p>{% endif %}
"""


def open_instrument(address=None, timeout=5):
	"""Attempt to open a connection to a Keithley 2602.

	If `address` is provided it will be used. Otherwise we scan available
	resources, query *IDN? and pick the device that identifies as a 2602.
	"""
	if pyvisa is None:
		state.status = "pyvisa not installed"
		return

	try:
		state.rm = pyvisa.ResourceManager()
	except Exception as e:
		state.status = f"failed to create ResourceManager: {e}"
		return

	resources = []
	try:
		resources = list(state.rm.list_resources())
	except Exception as e:
		state.status = f"failed to list resources: {e}"
		return

	# If explicit address given, try that first
	try_order = []
	if address:
		try_order.append(address)
	try_order.extend(r for r in resources if r not in try_order)

	for res in try_order:
		try:
			inst = state.rm.open_resource(res, timeout=timeout*1000)
			# Some instruments require a short delay before querying
			try:
				idn = inst.query("*IDN?").strip()
			except Exception:
				idn = None

			if idn and "2602" in idn:
				state.inst = inst
				state.status = "opened"
				state.idn = idn
				return
			else:
				# close and continue
				try:
					inst.close()
				except Exception:
					pass
		except Exception:
			continue

	state.status = "no Keithley 2602 found"


@app.route("/")
def index():
	return render_template_string(INDEX_HTML, status=state.status, idn=state.idn)


def start_connection_background():
	# Read address from env var if present
	address = os.environ.get("KEITHLEY_ADDRESS")
	open_instrument(address=address)


if __name__ == "__main__":
	# Start connection attempt in background so Flask can start immediately
	t = threading.Thread(target=start_connection_background, daemon=True)
	t.start()
	# Run Flask app
	app.run(host="0.0.0.0", port=5000, debug=True)

