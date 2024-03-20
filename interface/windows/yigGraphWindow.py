from interface.windows.graphWindow import GraphWindow


class PowerIFGraphWindow(GraphWindow):
    window_title = "P-IF Graphs"
    graph_title = "Power (IF)"
    y_label = "Power, dBm"
    x_label = "IF, GHz"


class YIFGraphWindow(GraphWindow):
    window_title = "Y-IF Graphs"
    graph_title = "Y (IF)"
    x_label = "IF, GHz"
    y_label = "Y, dBm"


class TnIFGraphWindow(GraphWindow):
    window_title = "Tn-IF Graphs"
    graph_title = "Tn (IF)"
    x_label = "IF, GHz"
    y_label = "Tn, K"
