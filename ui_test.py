import sys
import os
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl
from PyQt5 import uic
from graph_builder import GraphBuilder

def on_render_pressed(selection):
    print(f"render button pressed {selection}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi("Main.ui", self)

        self.video_widget = QVideoWidget(self.videoFrame)
        layout = QVBoxLayout(self.videoFrame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_widget)

        scenario_dir = Path("scenarios")

        files = [
            file.stem
            for file in scenario_dir.iterdir()
            if file.is_file() and file.suffix == ".txt"
        ]

        self.comboBox.clear()
        self.comboBox.addItems(sorted(files))

        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.video_widget)

        video_path = os.path.abspath("output.mp4")
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(video_path)))

        self.graph_builder = GraphBuilder(self.xAxisCombo, self.yAxisCombo, self.graphDisplay)

        self.playButton.clicked.connect(self.player.play)
        self.stopButton.clicked.connect(self.player.stop)
        self.pushButton.clicked.connect(self.on_render)
        self.graphButton.clicked.connect(self.graph_builder.build_graph)
        self.quitButton.clicked.connect(app.quit)

    def on_render(self):
        on_render_pressed(self.comboBox.currentText())

app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec_())
