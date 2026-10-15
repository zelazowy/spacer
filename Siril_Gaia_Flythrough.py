"""Siril Gaia Fly-through — current plate-solved FITS/TIFF to MP4."""
import sys
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
import threading
import traceback

import sirilpy as s
s.ensure_installed('numpy','scipy','astropy','Pillow','tifffile','PyQt6')
sys.path.insert(0,str(Path(__file__).resolve().parent/'gaia_flythrough'))
from version import VERSION, field_description
from siril_pipeline import normalized_pixels, parse_header, has_solution, find_tool, run_pipeline, render_prepared, load_prepared_scene, UNSOLVED_MESSAGE
from astropy.time import Time
from PyQt6.QtCore import QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication,QWidget,QVBoxLayout,QFormLayout,QHBoxLayout,
    QLabel,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QPushButton,QFileDialog,
    QMessageBox,QPlainTextEdit)


class Worker(QThread):
    progress=pyqtSignal(str)
    completed=pyqtSignal(str)
    failed=pyqtSignal(str)
    def __init__(self,pixels,header,options):
        super().__init__()
        self.pixels,self.header,self.options=pixels,header,options
        self.cancel=threading.Event()
    def run(self):
        try:
            if getattr(self.options,'reuse',False):
                out=render_prepared(self.options.output,self.options,self.progress.emit,self.cancel)
            else:
                out=run_pipeline(self.pixels,self.header,self.options,self.progress.emit,self.cancel)
            self.completed.emit(str(out))
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class FlythroughWindow(QWidget):
    def __init__(self,siril):
        super().__init__()
        self.siril=siril;self.worker=None;self.result=None;self.prepared=None;self.result_stem=None
        self.setWindowTitle(f'SPACER — v{VERSION}')
        self.resize(740,620)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Use the current plate-solved image. Processing uses a copy; the Siril image stays unchanged.'))
        form=QFormLayout();layout.addLayout(form)
        self.seconds=QSpinBox();self.seconds.setRange(4,600);self.seconds.setValue(60)
        self.seconds.setSuffix(' s');form.addRow('Duration',self.seconds)
        self.zoom=QDoubleSpinBox();self.zoom.setRange(0,10000);self.zoom.setValue(30)
        self.zoom.setSuffix(' %');form.addRow('Final zoom increase',self.zoom)
        self.mode=QComboBox()
        self.mode.addItem('Natural — fitted cores; complex stars stay flat','natural')
        self.mode.addItem('Dynamic — original patches; blends may move together','dynamic')
        self.mode.addItem('Iterative (experimental) — refit isolated bright-star groups','iterative')
        form.addRow('Scene style',self.mode)
        self.stretch=QComboBox();self.stretch.addItems(['Current pixels (already stretched)','Linked autostretch for a linear image'])
        form.addRow('Image preparation',self.stretch)
        self.engine=QComboBox();self.engine.addItems(['StarXTerminator','StarNet 2.5+'])
        form.addRow('Star removal',self.engine)
        self.executable=QLineEdit();form.addRow('Star-removal executable',self.path_row(self.executable,False))
        self.engine.currentIndexChanged.connect(self.choose_engine);self.choose_engine()
        self.ffmpeg=QLineEdit(find_tool('ffmpeg'));form.addRow('FFmpeg executable',self.path_row(self.ffmpeg,False))
        self.epoch=QLineEdit();self.epoch.setPlaceholderText('Uses DATE-OBS; enter YYYY-MM-DD if missing')
        form.addRow('Observation date',self.epoch)
        name=siril.get_image_filename() or 'image'
        self.output=QLineEdit(str(Path(name).expanduser().resolve().parent/'flythrough'/f'{Path(name).stem}_{datetime.now():%Y%m%d_%H%M%S}'))
        form.addRow('Run folder (new or prepared)',self.path_row(self.output,True))
        layout.addWidget(QLabel('24 fps · 1920 px wide · 80 pc travel · 1.5 s easing at each end\nPrepare once, then change duration/zoom and render additional named versions.\n100% zoom = 2× · 900% = 10×. Gaia lookup requires internet for preparation.'))
        self.buttons=QHBoxLayout();layout.addLayout(self.buttons)
        self.start=QPushButton('Create flight');self.start.clicked.connect(self.begin);self.buttons.addWidget(self.start)
        self.variant=QPushButton('Render another version');self.variant.setEnabled(False)
        self.variant.clicked.connect(self.render_variant);self.buttons.addWidget(self.variant)
        self.cancel_button=QPushButton('Cancel');self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel);self.buttons.addWidget(self.cancel_button)
        self.preview=QPushButton('Open preview');self.preview.setEnabled(False)
        self.preview.clicked.connect(lambda: self.open_result('preview.html'));self.buttons.addWidget(self.preview)
        self.video=QPushButton('Open video');self.video.setEnabled(False)
        self.video.clicked.connect(lambda: self.open_result('flight.mp4'));self.buttons.addWidget(self.video)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);layout.addWidget(self.log)
        self.load_scene=QPushButton('Load prepared field…');self.load_scene.clicked.connect(self.load_prepared)
        layout.addWidget(self.load_scene)
        self.log.appendPlainText('Ready. Select linked autostretch if the actual pixels are linear; Siril’s display stretch alone is not saved.')
        self.settings=[self.seconds,self.zoom,self.mode,self.stretch,self.engine,self.executable,self.ffmpeg,self.epoch,self.output]
    def path_row(self,field,directory):
        host=QWidget();row=QHBoxLayout(host);row.setContentsMargins(0,0,0,0)
        row.addWidget(field);button=QPushButton('Browse…');row.addWidget(button)
        def browse():
            if directory:
                selected=QFileDialog.getExistingDirectory(self,'Choose a prepared run folder, or a parent folder for a new run')
                if selected:
                    folder=Path(selected)
                    if (folder/'scene.json').is_file() or (folder/'preview.html').is_file():
                        try: self.use_prepared(folder)
                        except Exception as exc: QMessageBox.warning(self,'Prepared field missing',str(exc))
                    else: field.setText(str(folder/'flythrough'/f'flight_{datetime.now():%Y%m%d_%H%M%S}'))
            else:
                selected,_=QFileDialog.getOpenFileName(self,'Choose executable')
                if selected: field.setText(selected)
        button.clicked.connect(browse)
        return host
    def choose_engine(self,*_):
        self.executable.setText(find_tool('rc-astro' if self.engine.currentIndex()==0 else 'starnet2'))
    def begin(self):
        try:
            import os
            if not self.output.text().strip(): raise ValueError('Choose a run folder.')
            out=Path(self.output.text()).expanduser()
            if out.exists():
                self.use_prepared(out)
                self.render_variant()
                return
            for label,field in [('Star-removal',self.executable),('FFmpeg',self.ffmpeg)]:
                if not Path(field.text()).is_file() or not os.access(field.text(),os.X_OK):
                    raise ValueError(f'{label} executable is missing or not executable. Choose its installed CLI.')
            with self.siril.image_lock():
                source=self.siril.get_image_filename() or 'unsaved'
                header=parse_header(self.siril.get_image_fits_header(),require_solution=False)
                pixels=self.siril.get_image_pixeldata(preview=self.stretch.currentIndex()==1,linked=True)
                if pixels is None: raise ValueError('No image is loaded.')
                pixels=normalized_pixels(pixels).copy()
            if not has_solution(header):
                raise ValueError(UNSOLVED_MESSAGE)
            date=self.epoch.text().strip() or header.get('DATE-OBS')
            if not date: raise ValueError('Enter the observation date; this image has no DATE-OBS.')
            Time(date)
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom.value(),mode=self.mode.currentData(),
                engine='StarXTerminator' if self.engine.currentIndex()==0 else 'StarNet',
                executable=str(Path(self.executable.text()).resolve()),ffmpeg=str(Path(self.ffmpeg.text()).resolve()),
                epoch=str(date),output=str(out),source=source)
            self.launch(pixels,header,options)
        except Exception as exc: QMessageBox.critical(self,'Cannot create flight',str(exc))
    def launch(self,pixels,header,options):
            self.prepared=Path(options.output).expanduser().resolve()
            self.result=None;self.preview.setEnabled(False);self.video.setEnabled(False)
            self.start.setEnabled(False);self.cancel_button.setEnabled(True)
            self.variant.setEnabled(False);self.load_scene.setEnabled(False)
            for control in self.settings: control.setEnabled(False)
            self.log.appendPlainText('Outputs: '+str(self.prepared))
            self.worker=Worker(pixels,header,options)
            self.worker.progress.connect(self.log.appendPlainText)
            self.worker.completed.connect(self.completed);self.worker.failed.connect(self.failed)
            self.worker.finished.connect(self.finished);self.worker.start()
    def render_variant(self):
        try:
            import os
            if not self.prepared or not (self.prepared/'scene.json').is_file():
                raise ValueError('Create a flight or load a prepared field first.')
            if not os.access(self.ffmpeg.text(),os.X_OK): raise ValueError('Choose the FFmpeg executable.')
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom.value(),mode=self.mode.currentData(),
                output=str(self.prepared),ffmpeg=self.ffmpeg.text(),reuse=True)
            self.launch(None,None,options)
        except Exception as exc: QMessageBox.critical(self,'Cannot render variant',str(exc))
    def load_prepared(self):
        selected=QFileDialog.getExistingDirectory(self,'Choose a flythrough run folder containing scene.json')
        if not selected: return
        try: self.use_prepared(Path(selected))
        except Exception as exc:
            QMessageBox.warning(self,'Prepared field missing',str(exc));return
    def use_prepared(self,folder):
        folder=Path(folder).expanduser().resolve()
        saved_scene=load_prepared_scene(folder)
        self.prepared=folder;self.output.setText(str(folder));self.variant.setEnabled(True)
        self.log.appendPlainText(f'Tool v{VERSION} · saved field {field_description(saved_scene)}\nReusing saved image and Gaia field: '+str(folder)+
            '\nThe current Siril image and star-removal settings are not used for this render.')
    def cancel(self):
        if self.worker:
            self.worker.cancel.set();self.cancel_button.setEnabled(False)
            self.log.appendPlainText('Cancellation requested. A catalogue query may take up to five minutes to finish.')
    def completed(self,path):
        self.result=Path(path);self.result_stem=self.worker.options.result_stem
        self.log.appendPlainText('Finished: '+str(self.result/(self.result_stem+'.mp4')))
        self.preview.setEnabled(True);self.video.setEnabled(True)
    def failed(self,message):
        self.log.appendPlainText(message)
        QMessageBox.warning(self,'Flight not completed',message)
    def finished(self):
        self.start.setEnabled(True);self.cancel_button.setEnabled(False)
        self.variant.setEnabled(bool(self.prepared and (self.prepared/'scene.json').is_file()))
        self.load_scene.setEnabled(True)
        for control in self.settings: control.setEnabled(True)
    def open_result(self,name):
        if self.result:
            suffix='.html' if name=='preview.html' else '.mp4'
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result/(self.result_stem+suffix))))
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.log.appendPlainText('Cancel and wait for the worker before closing.');event.ignore()
        else: event.accept()


def main():
    app=QApplication.instance() or QApplication(sys.argv)
    siril=s.SirilInterface()
    try:
        siril.connect()
        window=FlythroughWindow(siril);window.show();app.exec()
    except Exception as exc:
        traceback.print_exc();QMessageBox.critical(None,'Gaia Fly-through',str(exc))
    finally:
        if siril.connected: siril.disconnect()


if __name__=='__main__': main()
