from config import VNA_ADDRESS, VNA_SPARAM


from RsInstrument import *

instr = RsInstrument(f'TCPIP::{VNA_ADDRESS}::INSTR', id_query=True, reset=True)
idn = instr.query_str('*IDN?')
print('Hello, I am: ' + idn)
