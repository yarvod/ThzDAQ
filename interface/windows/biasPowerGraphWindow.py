from interface.windows.graphWindow import GraphWindow


class BiasPowerGraphWindow(GraphWindow):
    window_title = "Bias Power Graphs"
    graph_title = "Power (Bias Voltage)"
    x_label = "Bias Voltage, mV"
    y_label = "Power, dBm"


class GridBiasPowerGraphWindow(GraphWindow):
    window_title = "GRID P-V Graphs"
    graph_title = "Power (Voltage)"
    x_label = "Voltage, mV"
    y_label = "Power, dBm"


class GridBiasGraphWindow(GraphWindow):
    window_title = "GRID I-V Graphs"
    graph_title = "Current (Voltage)"
    x_label = "Voltage, mV"
    y_label = "Current, mkA"


class GridBiasPowerDiffGraphWindow(GraphWindow):
    window_title = "GRID Diff P-V Graphs"
    graph_title = "Power (Voltage)"
    x_label = "Voltage, mV"
    y_label = "Power, dBm"
