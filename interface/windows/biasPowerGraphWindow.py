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


class GridBiasPowerGraphWindow(GraphWindow):
    window_title = "GRID P-V Graphs"
    graph_title = "Power (Voltage)"
    x_label = "Voltage, mV"
    y_label = "Power, dBm"


class GridBiasCurrentGraphWindow(GraphWindow):
    window_title = "GRID I-V Graphs"
    graph_title = "Current (Voltage)"
    x_label = "Voltage, mV"
    y_label = "Current, mkA"


class GridBiasPowerDiffGraphWindow(GraphWindow):
    window_title = "GRID Y-factor P-V Graphs"
    graph_title = "Y-factor (Voltage)"
    x_label = "Voltage, mV"
    y_label = "Power, dBm"
