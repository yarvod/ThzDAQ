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
        self._create_block_tab(nb)

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

    def _create_block_tab(self, nb):
        frame = Frame(nb, name='sis block')

        block_frame = Frame(frame)
        block_frame.pack()

        self.iv_point_num = StringVar()
        Label(block_frame, text='Point num:').grid(row=0, column=0, padx=5, pady=5)
        Entry(block_frame, textvariable=self.iv_point_num).grid(row=0, column=1, padx=5, pady=5)

        self.bias_volt = StringVar()
        Label(block_frame, text='Bias Volt, V:').grid(row=0, column=2, padx=5, pady=5)
        Entry(block_frame, textvariable=self.bias_volt).grid(row=0, column=3, padx=5, pady=5)

        self.bias_curr = StringVar()
        Label(block_frame, text='Bias Curr, A').grid(row=0, column=4, padx=5, pady=5)
        Entry(block_frame, textvariable=self.bias_curr).grid(row=0, column=5, padx=5, pady=5)

        Button(block_frame, text='Measure curve', command=lambda: self.meas_iv_new(save=True)) \
            .grid(row=1, column=0, padx=5, pady=5)


        self.use_offset = BooleanVar()
        Checkbutton(block_frame, text='Use offset', var=self.use_offset).grid(row=2, column=0, padx=5, pady=5)

        Button(block_frame, text='Calculate offset', command=lambda: self.calc_offset()) \
            .grid(row=2, column=1, padx=5, pady=5)

        Button(block_frame, text='set 0', command=lambda: self.niblock.set_zero()) \
            .grid(row=3, column=0, padx=5, pady=5)

        Button(block_frame, text='update params', command=lambda: self.niblock.update_params()) \
            .grid(row=3, column=1, padx=5, pady=5)

        nb.add(frame, text='SIS block', underline=0, padding=2)


if __name__ == '__main__':
    UI().mainloop()
