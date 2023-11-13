from interface.windows.graphWindow import GraphWindow


class PowerIFGraphWindow(GraphWindow):
    window_title = "P-IF Graphs"
    graph_title = "Power (IF)"
    y_label = "Power, dBm"
    x_label = "IF, GHz"


class PowerIFDiffGraphWindow(GraphWindow):
    window_title = "Diff P-IF Graphs"
    graph_title = "Power (IF)"
    x_label = "IF, GHz"
    y_label = "Power, dBm"
