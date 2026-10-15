"""Siril Gaia Fly-through — current plate-solved FITS/TIFF to MP4."""
import sys
from pathlib import Path
from types import SimpleNamespace
import threading
import traceback

import sirilpy as s
s.ensure_installed('numpy','scipy','astropy','Pillow','tifffile','PyQt6')
sys.path.insert(0,str(Path(__file__).resolve().parent/'gaia_flythrough'))
from version import VERSION, field_description
from siril_pipeline import normalized_pixels, parse_header, has_solution, find_tool, run_pipeline, render_prepared, load_prepared_scene, read_project, resume_project, UNSOLVED_MESSAGE
from astropy.time import Time
from PyQt6.QtCore import QThread, pyqtSignal, QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication,QWidget,QVBoxLayout,QFormLayout,QHBoxLayout,
    QLabel,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QPushButton,QFileDialog,
    QMessageBox,QPlainTextEdit,QGroupBox,QToolButton,QProgressBar,QSizePolicy,QDialog,QDialogButtonBox,QScrollArea)


class ZoomSpinBox(QDoubleSpinBox):
    """Show a direct scale without trailing zeroes, using the system locale."""
    def textFromValue(self,value):
        return self.locale().toString(value,'f',3).rstrip('0').rstrip(self.locale().decimalPoint())


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
                out=resume_project(self.options.output,self.options,self.progress.emit,self.cancel)
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
        self.resize(680,560)
        self.setMinimumWidth(600)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,20,24,20);layout.setSpacing(16)
        heading=QLabel('SPACER');font=heading.font();font.setPointSize(24);font.setBold(True);heading.setFont(font)
        layout.addWidget(heading)
        subtitle=QLabel('A walk through your astrophotography.');layout.addWidget(subtitle)

        self.project_group=QGroupBox('Project');project_layout=QVBoxLayout(self.project_group)
        project_layout.setContentsMargins(16,16,16,16);project_layout.setSpacing(10)
        self.project_title=QLabel();self.project_title.setWordWrap(True);font=self.project_title.font();font.setBold(True);self.project_title.setFont(font)
        project_layout.addWidget(self.project_title)
        self.project_hint=QLabel();self.project_hint.setWordWrap(True);project_layout.addWidget(self.project_hint)
        project_actions=QHBoxLayout()
        self.load_scene=QPushButton('Open project…');self.load_scene.clicked.connect(self.load_prepared)
        self.new_project=QPushButton('New from Siril…');self.new_project.clicked.connect(self.new_from_siril)
        project_actions.addWidget(self.load_scene);project_actions.addWidget(self.new_project);project_actions.addStretch()
        project_layout.addLayout(project_actions);layout.addWidget(self.project_group)

        self.flight_group=QGroupBox('Flight');form=QFormLayout(self.flight_group)
        form.setContentsMargins(16,16,16,16);form.setVerticalSpacing(12)
        self.seconds=QSpinBox();self.seconds.setRange(4,600);self.seconds.setValue(60)
        self.seconds.setSuffix(' s');form.addRow('Duration',self.seconds)
        self.zoom=ZoomSpinBox();self.zoom.setDecimals(3);self.zoom.setRange(1,101)
        self.zoom.setSingleStep(.1);self.zoom.setValue(1.3);self.zoom.setSuffix('×')
        form.addRow('Final zoom',self.zoom)
        form.addRow(QLabel('24 fps · up to 1920 px wide · Iterative scene'))
        layout.addWidget(self.flight_group)

        self.advanced=QWidget();advanced_layout=QFormLayout(self.advanced)
        advanced_layout.setContentsMargins(0,8,0,0);advanced_layout.setVerticalSpacing(10)
        self.preparation=QGroupBox('First preparation only');prep=QFormLayout(self.preparation)
        self.stretch=QComboBox();self.stretch.addItems(['Current pixels (already stretched)','Linked autostretch (linear image)'])
        prep.addRow('Image pixels',self.stretch)
        self.engine=QComboBox();self.engine.addItems(['StarXTerminator','StarNet 2.5+'])
        prep.addRow('Star removal',self.engine)
        self.executable=QLineEdit();prep.addRow('Engine executable',self.path_row(self.executable,False))
        self.engine.currentIndexChanged.connect(self.choose_engine);self.choose_engine()
        if not self.executable.text() and find_tool('starnet2'): self.engine.setCurrentIndex(1)
        self.epoch=QLineEdit();self.epoch.setPlaceholderText('Automatic from image; override with YYYY-MM-DD')
        prep.addRow('Observation date',self.epoch)
        note=QLabel('Uses a copy of the current Siril pixels. First preparation needs internet for Gaia.\nIterative separation is experimental; ambiguous star groups remain flat.')
        note.setWordWrap(True);prep.addRow(note);advanced_layout.addRow(self.preparation)
        self.ffmpeg=QLineEdit(find_tool('ffmpeg'));advanced_layout.addRow('FFmpeg',self.path_row(self.ffmpeg,False))
        name=siril.get_image_filename() or 'image'
        self.output=QLineEdit(str(Path(name).expanduser().resolve().parent/'flythrough'/Path(name).stem))
        self.output.setPlaceholderText('Choose a project folder')
        advanced_layout.addRow('Project folder',self.path_row(self.output,True))
        self.advanced_toggle=self.disclosure(layout,'Advanced settings',self.advanced)

        self.status=QLabel('Ready to prepare this image.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress_bar=QProgressBar();self.progress_bar.setRange(0,0);self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4);self.progress_bar.hide();layout.addWidget(self.progress_bar)
        self.buttons=QHBoxLayout();layout.addLayout(self.buttons)
        self.preview=QPushButton('Open preview');self.preview.setEnabled(False)
        self.preview.clicked.connect(lambda: self.open_result('preview.html'));self.buttons.addWidget(self.preview)
        self.video=QPushButton('Open video');self.video.setEnabled(False)
        self.video.clicked.connect(lambda: self.open_result('flight.mp4'));self.buttons.addWidget(self.video)
        self.buttons.addStretch()
        self.cancel_button=QPushButton('Cancel');self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel);self.buttons.addWidget(self.cancel_button)
        self.start=QPushButton('Prepare and render');self.start.setDefault(True)
        self.start.setMinimumHeight(34);self.start.clicked.connect(self.begin);self.buttons.addWidget(self.start)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(2000)
        self.log.setMinimumHeight(130);self.log.setMaximumHeight(200)
        self.log.setAccessibleName('Processing details')
        self.details_toggle=self.disclosure(layout,'Details',self.log)
        self.log.appendPlainText('Ready. Current pixels are used by default. For a linear image, select linked autostretch in Advanced settings.')
        self.settings=[self.flight_group,self.advanced,self.project_group]
        self.output.editingFinished.connect(self.refresh_project)
        self.refresh_project()
        if Path(self.output.text()).exists():
            try: self.use_prepared(Path(self.output.text()))
            except (ValueError,OSError) as exc: self.status.setText(str(exc))

    def disclosure(self,layout,title,content):
        toggle=QToolButton();toggle.setText(title);toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.ArrowType.RightArrow);toggle.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
        content.hide()
        if title=='Advanced settings':
            toggle.setText('Advanced settings…');toggle.setArrowType(Qt.ArrowType.NoArrow)
            dialog=QDialog(self);dialog.setWindowTitle('Advanced settings');dialog.resize(700,440)
            body=QVBoxLayout(dialog)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(content);content.show();body.addWidget(scroll)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.close);body.addWidget(buttons)
            toggle.toggled.connect(lambda opened: dialog.show() if opened else dialog.hide())
            dialog.finished.connect(lambda _: toggle.setChecked(False))
            self.advanced_dialog=dialog
            layout.addWidget(toggle)
            return toggle
        def changed(opened):
            content.setVisible(opened)
            toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
            self.resize(self.width(),self.sizeHint().height())
        toggle.toggled.connect(changed);layout.addWidget(toggle);layout.addWidget(content)
        return toggle

    def zoom_percent(self):
        # Keep the existing project/export contract while presenting direct scale.
        return round((self.zoom.value()-1)*100,1)

    def refresh_project(self):
        folder=Path(self.output.text()).expanduser().resolve()
        saved=any((folder/name).is_file() for name in ('project.json','scene.json','scene_iterative.json','preview.html'))
        self.project_title.setText(folder.name if saved else Path(self.siril.get_image_filename() or 'Unsaved image').name)
        self.project_title.setToolTip(str(folder))
        ready=(folder/'scene_iterative.json').is_file()
        self.project_hint.setText(('Saved image · ready to render; analysis is reused.' if ready else 'Saved image · missing preparation steps will resume.') if saved else
            'Current Siril image · uses current pixels. For a linear image, choose autostretch in Advanced settings.')
        self.project_hint.setToolTip(str(folder))
        self.preparation.setEnabled(not saved)
        self.start.setText(('Render flight' if ready else 'Resume and render') if saved else 'Prepare and render')
        if folder!=self.prepared:
            self.result=None;self.result_stem=None
            self.preview.setEnabled(False);self.video.setEnabled(False)
        self.status.setText('Ready to render from the saved project.' if saved else 'Ready to prepare this image.')

    def new_from_siril(self):
        name=Path(self.siril.get_image_filename() or 'image').stem
        dialog=QFileDialog(self,'New project folder',str(Path(self.output.text()).parent))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setOption(QFileDialog.Option.DontConfirmOverwrite,True)
        dialog.setLabelText(QFileDialog.DialogLabel.Accept,'Use folder')
        dialog.selectFile(name+'_project')
        if not dialog.exec(): return
        selected=dialog.selectedFiles()[0]
        folder=Path(selected)
        if folder.exists():
            QMessageBox.information(self,'Choose a new folder','Choose a folder name that does not exist yet. Use Open project to return to an existing project.')
            return
        self.prepared=None;self.epoch.clear();self.output.setText(str(folder));self.refresh_project()
        self.advanced_toggle.setChecked(True)

    def report_progress(self,message):
        self.log.appendPlainText(message)
        self.status.setText(message if len(message)<160 else message[:157]+'…')

    def show_problem(self,title,message):
        self.status.setText(message)
        self.advanced_toggle.setChecked(True)
        QMessageBox.warning(self,title,message)

    def path_row(self,field,directory):
        host=QWidget();row=QHBoxLayout(host);row.setContentsMargins(0,0,0,0)
        row.addWidget(field);button=QPushButton('Browse…');row.addWidget(button)
        def browse():
            if directory:
                selected=QFileDialog.getExistingDirectory(self,'Choose a project folder')
                if selected:
                    folder=Path(selected)
                    if any((folder/name).is_file() for name in ('project.json','scene.json','preview.html','scene_iterative.json')):
                        try: self.use_prepared(folder)
                        except Exception as exc: QMessageBox.warning(self,'Prepared field missing',str(exc))
                    else:
                        field.setText(str(folder));self.refresh_project()
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
            if not self.output.text().strip(): raise ValueError('Choose a project folder in Advanced settings.')
            out=Path(self.output.text()).expanduser()
            if out.exists():
                self.use_prepared(out,restore=False)
                self.render_variant()
                return
            for label,field in [('Star-removal',self.executable),('FFmpeg',self.ffmpeg)]:
                if not Path(field.text()).is_file() or not os.access(field.text(),os.X_OK):
                    self.advanced_toggle.setChecked(True);field.setFocus()
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
            if not date:
                self.advanced_toggle.setChecked(True);self.epoch.setFocus()
                raise ValueError('Enter the observation date in Advanced settings; this image has no DATE-OBS.')
            Time(date)
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom_percent(),mode="iterative",
                engine='StarXTerminator' if self.engine.currentIndex()==0 else 'StarNet',
                executable=str(Path(self.executable.text()).resolve()),ffmpeg=str(Path(self.ffmpeg.text()).resolve()),
                epoch=str(date),output=str(out),source=source)
            self.launch(pixels,header,options)
        except Exception as exc: self.show_problem('Cannot render flight',str(exc))
    def launch(self,pixels,header,options):
            self.prepared=Path(options.output).expanduser().resolve()
            self.result=None;self.preview.setEnabled(False);self.video.setEnabled(False)
            self.start.setEnabled(False);self.advanced_toggle.setEnabled(False);self.cancel_button.setEnabled(True);self.cancel_button.show()
            self.advanced_dialog.close();self.start.setText('Processing…')
            self.progress_bar.show();self.status.setText('Starting…')
            self.load_scene.setEnabled(False)
            for control in self.settings: control.setEnabled(False)
            self.log.appendPlainText('Outputs: '+str(self.prepared))
            self.worker=Worker(pixels,header,options)
            self.worker.progress.connect(self.report_progress)
            self.worker.completed.connect(self.completed);self.worker.failed.connect(self.failed)
            self.worker.finished.connect(self.finished);self.worker.start()
    def render_variant(self):
        try:
            import os
            selected=Path(self.output.text()).expanduser().resolve()
            if selected!=self.prepared:
                self.use_prepared(selected,restore=False)
            if not self.prepared:
                raise ValueError('Create a flight or load a prepared field first.')
            if not Path(self.ffmpeg.text()).is_file() or not os.access(self.ffmpeg.text(),os.X_OK):
                raise ValueError('Choose the FFmpeg executable in Advanced settings.')
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom_percent(),mode="iterative",
                output=str(self.prepared),ffmpeg=self.ffmpeg.text(),reuse=True)
            self.launch(None,None,options)
        except Exception as exc: self.show_problem('Cannot render flight',str(exc))
    def load_prepared(self):
        selected=QFileDialog.getExistingDirectory(self,'Choose a SPACER project or an older prepared run folder')
        if not selected: return
        try: self.use_prepared(Path(selected))
        except Exception as exc:
            QMessageBox.warning(self,'Prepared field missing',str(exc));return
    def use_prepared(self,folder,restore=True):
        folder=Path(folder).expanduser().resolve()
        state=read_project(folder)
        if (folder/'scene_iterative.json').exists():
            import json
            saved_scene=json.loads((folder/'scene_iterative.json').read_text())
        else:
            saved_scene=load_prepared_scene(folder) if (folder/'scene.json').exists() or (folder/'preview.html').exists() else {}
        if not saved_scene and not state and not (folder/'scene_iterative.json').exists():
            raise ValueError('This folder is not a SPACER project.')
        if restore:
            self.seconds.setValue(state.get('seconds',60))
            self.zoom.setValue(1+state.get('zoom',30)/100)
            if state.get('ffmpeg'): self.ffmpeg.setText(state['ffmpeg'])
        self.result_stem=state.get('last_render')
        self.result=folder if self.result_stem else None
        self.preview.setEnabled(bool(self.result and (folder/(self.result_stem+'.html')).exists()))
        self.video.setEnabled(bool(self.result and (folder/(self.result_stem+'.mp4')).exists()))
        self.prepared=folder;self.output.setText(str(folder));self.refresh_project()
        self.log.appendPlainText(f'Tool v{VERSION} · saved field {field_description(saved_scene)}\nReusing saved image and Gaia field: '+str(folder)+
            '\nThe current Siril image and star-removal settings are not used for this render.')
    def cancel(self):
        if self.worker:
            self.worker.cancel.set();self.cancel_button.setEnabled(False)
            self.report_progress('Cancelling… Waiting for the current step to stop. A Gaia query may take up to five minutes.')
    def completed(self,path):
        self.result=Path(path);self.result_stem=self.worker.options.result_stem
        self.report_progress('Flight ready. Open the preview or video.');self.log.appendPlainText(str(self.result/(self.result_stem+'.mp4')))
        self.preview.setEnabled(True);self.video.setEnabled(True)
    def failed(self,message):
        if self.worker and self.worker.cancel.is_set():
            self.report_progress('Cancelled. Saved preparation and earlier exports are kept.');return
        self.report_progress(message);self.details_toggle.setChecked(True)
        QMessageBox.warning(self,'Flight not completed',message)
    def finished(self):
        self.start.setEnabled(True);self.advanced_toggle.setEnabled(True);self.cancel_button.setEnabled(False)
        self.cancel_button.hide();self.progress_bar.hide()
        self.load_scene.setEnabled(True)
        for control in self.settings: control.setEnabled(True)
        message=self.status.text()
        self.refresh_project()
        self.status.setText(message)
    def open_result(self,name):
        if self.result:
            suffix='.html' if name=='preview.html' else '.mp4'
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result/(self.result_stem+suffix))))
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.report_progress('A flight is still processing. Cancel and wait for it to stop before closing.');event.ignore()
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
