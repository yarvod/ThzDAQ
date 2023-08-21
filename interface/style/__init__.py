# Colors
from state import state

PALE_PURPLE = "#e5d4ed"
BLUE = "#6d72c3"
REBECCA_PURPLE = "#5941a9"
GRAY = "#514f59"
DARK_PURPLE = "#1d1128"

# Fonts
FONT_SIZE = "15px"

# Variables
BORDER_RADIUS = "5px"

GLOBAL_STYLE = """
QWidget {
    font-size: 15px;
}
QGroupBox {
    border: 1px solid #514f59;
    border-radius: 5px;
    padding-top: 10px;
    margin-top: 5ex;
}
QGroupBox:title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 10px 2px;
    left: 10px;
    color: #514f59;
}
QLabel {
    color: #464d55;
    font-weight: 600;
}
QLabel#heading {
    color: #0f1925;
    font-size: 18px;
    margin-bottom: 10px;
}
QLabel#subheading {
    color: #0f1925;
    font-size: 12px;
    font-weight: normal;
    margin-bottom: 10px;
}
QLineEdit {
    border-radius: 5px;
    border: 1px solid #e5d4ed;
    padding: 5px 15px;
}
QLineEdit:focus {
    border: 1px solid #6d72c3;
}
QLineEdit::placeholder {
    color: #767e89;
}
QDoubleSpinBox {
    border-radius: 5px;
    border: 1px solid #e5d4ed;
    padding: 5px 15px;
}
QDoubleSpinBox:focus {
    border: 1px solid #6d72c3;
}
QDoubleSpinBox::placeholder {
    color: #767e89;
}
QDoubleSpinBox::up-button {
    background: #e5d4ed;
    border-bottom: 1px solid white;
    border-top-right-radius: 5px;
    image: url(assets/up-arrow.png);
    width: 25px;
}
QDoubleSpinBox::up-button:hover {
    background: #6d72c3;
}
QDoubleSpinBox::down-button {
    background: #e5d4ed;
    border-top: 1px solid white;
    border-bottom-right-radius: 5px;
    image: url(assets/down-arrow.png);
    width: 25px;
}
QDoubleSpinBox::down-button:hover {
    background: #6d72c3;
}
"""
