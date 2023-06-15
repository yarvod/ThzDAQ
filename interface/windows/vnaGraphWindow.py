from interface.windows.graphWindow import GraphWindow


class VNAGraphWindow(GraphWindow):
    window_title = "Reflection Graphs VNA"
    graph_title = "Reflection (Intermediate frequency)"
    y_label = "Reflection level, dB"
    x_label = "Intermediate frequency, GHz"
