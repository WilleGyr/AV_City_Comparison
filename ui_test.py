import sys
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5 import uic

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi("Main.ui", self)

app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec_())