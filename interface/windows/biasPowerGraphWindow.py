from interface.windows.graphWindow import GraphWindow


class BiasPowerGraphWindow(GraphWindow):
    window_title = "P-V Graphs"
    graph_title = "Power (Voltage)"
    x_label = "Bias Voltage, mV"
    y_label = "Power, dBm"


class BiasPowerDiffGraphWindow(GraphWindow):
    window_title = "Y-factor P-V Graphs"
    graph_title = "Y-factor (Voltage)"
    x_label = "Voltage, mV"
    y_label = "Power, dBm"


class TnGraphWindow(GraphWindow):
    window_title = "Tn-V Graphs"
    graph_title = "Tn (Voltage)"
    x_label = "Voltage, mV"
    y_label = "Tn, K"
