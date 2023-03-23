from tkinter import *
from tkinter.ttk import Notebook

from config import BLOCK_ADDRESS, BLOCK_PORT


class BaseMixin:
    ...


class UI(Frame, BaseMixin):

    def __init__(self, isapp=True, name='control line manager'):
        Frame.__init__(self, name=name)
        self.pack(expand=Y, fill=BOTH)
        self.master.title('Control Line manager')
        self.isapp = isapp
        self._create_widgets()

    def _create_widgets(self):
        self._create_demo_panel()

    def _create_demo_panel(self):
        demo_panel = Frame(self, name='demo')
        demo_panel.pack(side=TOP, fill=BOTH, expand=Y)
        nb = Notebook(demo_panel, name='notebook')
        nb.enable_traversal()
        nb.pack(fill=BOTH, expand=Y, padx=2, pady=2)
        self._create_setup_tab(nb)
        # self._create_ctrl_tab(nb)

    def _create_setup_tab(self, nb):
        frame = Frame(nb, name='setup')
        self.block_address = StringVar(value=BLOCK_ADDRESS)
        self.block_port = StringVar(value=BLOCK_PORT)

        Label(frame, text='Block IP', font=('bold', '14')).grid(row=0, column=0, padx=5, pady=5, sticky=W)
        Entry(frame, textvariable=self.block_address).grid(row=0, column=1, padx=5, pady=5, sticky=W)
        Label(frame, text='Block PORT', font=('bold', '14')).grid(row=1, column=0, padx=5, pady=5, sticky=W)
        Entry(frame, textvariable=self.block_port).grid(row=1, column=1, padx=5, pady=5, sticky=W)

        frame.rowconfigure(1, weight=1)
        frame.columnconfigure((0, 1), weight=1, uniform=1)

        nb.add(frame, text='SetUp', underline=0, padding=2)


if __name__ == '__main__':
    UI().mainloop()
