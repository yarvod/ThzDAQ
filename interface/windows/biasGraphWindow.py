from interface.windows.graphWindow import GraphWindow


class BiasGraphWindow(GraphWindow):
    window_title = "I-V curve"
    graph_title = "I-V curve"
    x_label = "Bias Voltage, mV"
    y_label = "Bias Current, mkA"
