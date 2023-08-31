from interface.windows.graphWindow import GraphWindow


class VNAGraphWindow(GraphWindow):
    window_title = "Reflection Graphs VNA"
    graph_title = "Reflection (Frequency)"
    y_label = "Reflection level, dB"
    x_label = "Frequency, GHz"
