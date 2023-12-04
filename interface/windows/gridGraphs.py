from interface.windows.graphWindow import GraphWindow


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


class GridTnGraphWindow(GraphWindow):
    window_title = "GRID Tn-V Graphs"
    graph_title = "Tn (Voltage)"
    x_label = "Voltage, mV"
    y_label = "Tn, K"


class GridAngleCurrentGraphWindow(GraphWindow):
    window_title = "GRID I-A Graphs"
    graph_title = "Current (Angle)"
    x_label = "Angle, °"
    y_label = "Current, mkA"
