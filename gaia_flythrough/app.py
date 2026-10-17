"""Shared SPACER desktop interface; Siril is an optional image source."""
import sys
import math
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import threading
import traceback

from version import VERSION, field_description
from preferences import Preferences
from photo_date import infer_photo_date, date_info
from siril_pipeline import normalized_pixels, parse_header, has_solution, find_tool, run_pipeline, render_prepared, load_prepared_scene, read_project, resume_project, UNSOLVED_MESSAGE
from astropy.time import Time
from image_source import FileImageSource
from astap_solver import solve_project, find_astap, resolve_astap
from task_progress import Diagnostic
from density import DEFAULT_MAX_STARS, MAX_MOVING_STARS
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
    progress=pyqtSignal(str,bool)
    frame_progress=pyqtSignal(int,int,float)
    stage_progress=pyqtSignal(str,int,int,float)
    completed=pyqtSignal(str)
    failed=pyqtSignal(str)
    def __init__(self,pixels,header,options):
        super().__init__()
        self.pixels,self.header,self.options=pixels,header,options
        self.cancel=threading.Event()
        self.options.frame_progress=self.frame_progress.emit
        self.options.stage_progress=self.stage_progress.emit
    def report(self,message):
        detail=getattr(message,'detail',False)
        if not detail:
            print(f'[{datetime.now():%H:%M:%S}] {message}',flush=True)
        self.progress.emit(str(message),detail)

    def run(self):
        try:
            self.report('Project folder: '+str(self.options.output))
            if getattr(self.options,'solve',False):
                out=solve_project(self.options,self.report,self.cancel)
            elif getattr(self.options,'reuse',False):
                out=resume_project(self.options.output,self.options,self.report,self.cancel)
            else:
                out=run_pipeline(self.pixels,self.header,self.options,self.report,self.cancel)
            self.completed.emit(str(out))
        except Exception as exc:
            self.report(str(exc))
            self.report(Diagnostic(traceback.format_exc()))
            self.failed.emit(str(exc))


class FlythroughWindow(QWidget):
    def __init__(self,siril=None):
        super().__init__()
        self.siril=siril;self.file_source=None;self.worker=None;self.result=None;self.prepared=None;self.result_stem=None
        self.preferences=Preferences()
        self.auto_date_info=None
        self.render_succeeded=False
        self.setWindowTitle(f'SPACER — v{VERSION}')
        self.resize(680,560)
        self.setMinimumWidth(600)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,20,24,20);layout.setSpacing(16)
        self.header=QWidget();header_layout=QVBoxLayout(self.header)
        header_layout.setContentsMargins(0,0,0,0);header_layout.setSpacing(6)
        self.heading=QLabel('SPACER');font=self.heading.font();font.setPointSize(24);font.setBold(True);self.heading.setFont(font)
        self.subtitle=QLabel('A walk through your astrophotography.')
        for label in (self.heading,self.subtitle):
            label.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
            header_layout.addWidget(label)
        self.header.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
        layout.addWidget(self.header)

        self.project_group=QGroupBox('Project');project_layout=QVBoxLayout(self.project_group)
        project_layout.setContentsMargins(16,16,16,16);project_layout.setSpacing(10)
        self.project_title=QLabel();self.project_title.setWordWrap(True);font=self.project_title.font();font.setBold(True);self.project_title.setFont(font)
        project_layout.addWidget(self.project_title)
        self.project_hint=QLabel();self.project_hint.setWordWrap(True);project_layout.addWidget(self.project_hint)
        project_actions=QHBoxLayout()
        self.load_scene=QPushButton('Open project…');self.load_scene.clicked.connect(self.load_prepared)
        self.new_project=QPushButton('New from Siril…' if siril else 'Open image…');self.new_project.clicked.connect(self.new_from_siril if siril else self.open_image)
        project_actions.addWidget(self.load_scene);project_actions.addWidget(self.new_project);project_actions.addStretch()
        project_layout.addLayout(project_actions)
        self.coordinates=QWidget();coordinates_layout=QVBoxLayout(self.coordinates)
        coordinates_layout.setContentsMargins(0,6,0,0)
        self.coordinates_hint=QLabel();self.coordinates_hint.setWordWrap(True)
        self.coordinates_hint.setMinimumHeight(48)
        coordinates_layout.addWidget(self.coordinates_hint)
        self.target=QLineEdit();self.target.setPlaceholderText('e.g. NGC 2403 or M45')
        self.target.setToolTip('Optional object name (internet lookup), or RA/Dec in hours and degrees. A nearby target narrows the search.')
        target_form=QFormLayout();target_form.addRow('Object name (optional)',self.target)
        coordinates_layout.addLayout(target_form)
        self.choose_coordinates=QPushButton('Choose solved FITS…')
        self.choose_coordinates.clicked.connect(self.open_coordinates)
        self.solve_button=QPushButton('Solve sky position');self.solve_button.clicked.connect(self.solve_image)
        coordinates_layout.addWidget(self.solve_button,alignment=Qt.AlignmentFlag.AlignLeft)
        project_layout.addWidget(self.coordinates);self.coordinates.hide()
        layout.addWidget(self.project_group)

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
        advanced_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        prep.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.stretch=QComboBox();self.stretch.addItems(['Current pixels (already stretched)','Linked autostretch (linear image)'])
        if not siril:
            self.stretch.clear();self.stretch.addItem('File pixels (already stretched)')
        prep.addRow('Image pixels',self.stretch)
        self.engine=QComboBox();self.engine.addItems(['StarXTerminator','StarNet 2.5+'])
        prep.addRow('Star removal',self.engine)
        self.executable=QLineEdit();prep.addRow('Engine executable',self.path_row(self.executable,False))
        self.engine.currentIndexChanged.connect(self.choose_engine);self.choose_engine()
        if not self.executable.text() and find_tool('starnet2'): self.engine.setCurrentIndex(1)
        self.epoch=QLineEdit();self.epoch.setPlaceholderText('Automatic; override with YYYY or YYYY-MM-DD')
        prep.addRow('Observation date',self.epoch)
        self.date_origin=QLabel('Capture metadata is preferred; file dates are used as estimates.');self.date_origin.setWordWrap(True)
        prep.addRow(self.date_origin)
        self.epoch.textEdited.connect(self.update_date_origin)
        date_hint=QLabel('Approximate capture year is enough for ordinary matching. You can correct the detected date or enter just a year.')
        date_hint.setWordWrap(True);prep.addRow(date_hint)
        self.epoch.setToolTip('Gaia positions are corrected for stellar proper motion at this date. A nearby estimate is better than an unrelated date.')
        note=QLabel(('Uses a copy of the current Siril pixels.' if siril else 'Uses saved file pixels. Supply an already-stretched image.')+' First preparation needs internet for Gaia.\nIterative separation is experimental; ambiguous star groups remain flat.')
        note.setWordWrap(True);prep.addRow(note);advanced_layout.addRow(self.preparation)
        self.star_limit=QSpinBox();self.star_limit.setRange(100,MAX_MOVING_STARS);self.star_limit.setSingleStep(1000);self.star_limit.setValue(DEFAULT_MAX_STARS)
        self.star_limit.setToolTip('Fewer moving stars make preparation and rendering faster. Unselected stars stay in the photograph. Existing fields can use fewer stars; preparing additional stars needs a new project.')
        advanced_layout.addRow('Moving stars (maximum)',self.star_limit)
        self.solver_settings=QGroupBox('Plate solving (ASTAP)');solver_form=QFormLayout(self.solver_settings)
        solver_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.astap=QLineEdit(find_astap());solver_form.addRow('ASTAP executable',self.path_row(self.astap,False))
        self.database=QLineEdit('/usr/local/opt/astap' if Path('/usr/local/opt/astap').is_dir() else '')
        self.database.setPlaceholderText('Use ASTAP’s installed database')
        database_row=QWidget();database_layout=QHBoxLayout(database_row);database_layout.setContentsMargins(0,0,0,0)
        database_row.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        database_layout.addWidget(self.database,1);browse_database=QPushButton('Browse…')
        browse_database.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed);database_layout.addWidget(browse_database)
        def choose_database():
            selected=QFileDialog.getExistingDirectory(self,'Choose ASTAP star database folder')
            if selected: self.database.setText(selected)
        browse_database.clicked.connect(choose_database);solver_form.addRow('Star database',database_row)
        self.fov=QDoubleSpinBox();self.fov.setRange(0,180);self.fov.setDecimals(3);self.fov.setSuffix('°');self.fov.setSpecialValueText('Auto')
        solver_form.addRow('Image height on sky',self.fov)
        self.radius=QDoubleSpinBox();self.radius.setRange(.1,180);self.radius.setValue(180);self.radius.setSuffix('°')
        solver_form.addRow('Search radius',self.radius)
        self.binning=QSpinBox();self.binning.setRange(0,8);self.binning.setSpecialValueText('Auto')
        solver_form.addRow('Downsampling',self.binning)
        solver_note=QLabel('An installed ASTAP star database is required. Auto field height searches about 0.3–10°.\nObject-name lookup uses internet; blind solving and numeric coordinates work offline.')
        solver_note.setWordWrap(True);solver_form.addRow(solver_note)
        solver_form.addRow('Existing solution',self.choose_coordinates)
        if not siril: advanced_layout.addRow(self.solver_settings)
        else: self.solver_settings.hide()
        self.ffmpeg=QLineEdit(find_tool('ffmpeg'));advanced_layout.addRow('FFmpeg',self.path_row(self.ffmpeg,False))
        name=self.image_filename() or 'image'
        self.output=QLineEdit(str(Path(name).expanduser().resolve().parent/'flythrough'/Path(name).stem))
        self.output.setPlaceholderText('Choose a project folder')
        advanced_layout.addRow('Project folder',self.path_row(self.output,True))
        self.advanced_toggle=self.disclosure(layout,'Advanced settings',self.advanced)

        self.status=QLabel('Ready to prepare this image.');self.status.setWordWrap(True)
        self.status.setFixedHeight(self.status.fontMetrics().lineSpacing()*2+8)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        layout.addWidget(self.status)
        self.progress_bar=QProgressBar();self.progress_bar.setRange(0,0);self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(18);self.progress_bar.hide();layout.addWidget(self.progress_bar)
        self.render_counter=QLabel();self.render_counter.setWordWrap(True);self.render_counter.hide();layout.addWidget(self.render_counter)
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
        # Keep progress and action positions stable as text/counters appear.
        for control in (self.progress_bar,self.render_counter,self.cancel_button):
            policy=control.sizePolicy();policy.setRetainSizeWhenHidden(True);control.setSizePolicy(policy)
        self.render_counter.setFixedHeight(self.render_counter.fontMetrics().lineSpacing()*2+4)
        self.append_log('Ready. Open an image or a saved project.' if not siril else 'Ready. Current pixels are used by default. For a linear image, select linked autostretch in Advanced settings.')
        # Spare window height belongs below the content, never between labels.
        layout.addStretch(1)
        self.settings=[self.flight_group,self.advanced,self.project_group]
        self.output.editingFinished.connect(self.refresh_project)
        self.refresh_project()
        if self.siril: self.detect_siril_date()
        if self.image_filename() and Path(self.output.text()).exists():
            try: self.use_prepared(Path(self.output.text()))
            except (ValueError,OSError) as exc: self.status.setText(str(exc))

    def image_filename(self):
        if self.siril: return self.siril.get_image_filename()
        return str(self.file_source.path) if self.file_source else None

    def open_image(self):
        selected,_=QFileDialog.getOpenFileName(self,'Open a finished image',self.preferences.directory('image_directory'),filter='Images (*.fits *.fit *.fts *.tif *.tiff *.png *.jpg *.jpeg)')
        if not selected: return
        try: self.use_image(selected)
        except Exception as exc: self.show_problem('Cannot open image',str(exc))

    def open_coordinates(self):
        if not self.file_source: return
        selected,_=QFileDialog.getOpenFileName(self,'Sky coordinates — select a solved FITS of this same image',self.preferences.directory('reference_directory'),filter='Solved FITS (*.fits *.fit *.fts)')
        if not selected: return
        try:
            candidate=FileImageSource(self.file_source.path,selected)
            candidate.snapshot()  # Validate dimensions and pixels before accepting the reference.
            self.file_source=candidate;self.set_date_info(candidate.date_info());self.remember_image();self.preferences.save(reference_directory=str(Path(selected).resolve().parent));self.refresh_project()
        except Exception as exc:
            self.status.setText(str(exc))
            QMessageBox.warning(self,'Cannot use sky coordinates',str(exc))

    def use_image(self,path,wcs_path=None):
        source=FileImageSource(path,wcs_path)
        # Validate the header before changing the selected project.
        if source.has_coordinates: source.header()
        self.file_source=source;self.prepared=None;self.target.clear();self.set_date_info(source.date_info())
        self.output.setText(str(source.path.parent/'flythrough'/source.path.stem))
        self.refresh_project()
        self.remember_image()
        if Path(self.output.text()).exists(): self.use_prepared(Path(self.output.text()))

    def set_date_info(self,info):
        self.auto_date_info=info
        self.epoch.setText(info['value'].split('T')[0] if info else '')
        self.update_date_origin()

    def selected_date_info(self):
        text=self.epoch.text().strip()
        if self.auto_date_info and text in (self.auto_date_info['value'],self.auto_date_info['value'].split('T')[0]): return dict(self.auto_date_info)
        return date_info(text,'Manual date') if text else None

    def update_date_origin(self,*_):
        info=self.selected_date_info()
        if info:
            prefix='Estimated from ' if info['approximate'] else 'From '
            self.date_origin.setText(prefix+info['source']+'. You can override it.')
        else: self.date_origin.setText('No usable date found. Enter an approximate capture year.')

    def detect_siril_date(self):
        try:
            header=parse_header(self.siril.get_image_fits_header(),require_solution=False)
            self.set_date_info(infer_photo_date(self.image_filename() or '',header))
        except (AttributeError,ValueError,OSError): pass

    def remember_image(self):
        if self.siril or not self.file_source: return
        self.preferences.save(last_kind='image',last_image=str(self.file_source.path),
            last_wcs=str(self.file_source.wcs_path) if self.file_source.wcs_path else '',
            image_directory=str(self.file_source.path.parent))

    def remember_project(self,folder):
        folder=Path(folder).expanduser().resolve()
        self.preferences.save(last_kind='project',last_project=str(folder),project_directory=str(folder.parent))

    def restore_last(self):
        """Standalone startup only; never replace Siril input or explicit CLI arguments."""
        if self.siril: return
        state=self.preferences.data
        try:
            if state.get('last_kind')=='project':
                folder=state.get('last_project','')
                if not isinstance(folder,str) or not folder or not Path(folder).is_dir(): return
                self.use_prepared(Path(folder))
            elif state.get('last_kind')=='image':
                path=state.get('last_image','')
                if not isinstance(path,str) or not path or not Path(path).is_file(): return
                wcs=state.get('last_wcs','')
                wcs=wcs if isinstance(wcs,str) and wcs and Path(wcs).is_file() else None
                self.use_image(path,wcs)
        except (ValueError,OSError,TypeError) as exc:
            self.append_log('Could not reopen the last input: '+str(exc))

    def solve_image(self):
        try:
            if not self.file_source: raise ValueError('Open an image first.')
            resolve_astap(self.astap.text())
            if not self.output.text().strip(): raise ValueError('Choose a new project folder.')
            info=self.selected_date_info()
            if self.epoch.text().strip() and not info: raise ValueError('Enter a valid capture year or date.')
            if not info: info=self.file_source.date_info()
            date=info['value'] if info else ''
            options=SimpleNamespace(solve=True,output=self.output.text(),source=str(self.file_source.path),
                wcs_path=str(self.file_source.wcs_path) if self.file_source.wcs_path else None,
                astap=self.astap.text(),database=self.database.text().strip(),target=self.target.text().strip(),
                fov=self.fov.value(),radius=self.radius.value(),binning=self.binning.value(),epoch=str(date),date_info=info,
                seconds=self.seconds.value(),zoom=self.zoom_percent(),max_stars=self.star_limit.value(),ffmpeg=self.ffmpeg.text(),
                engine='StarXTerminator' if self.engine.currentIndex()==0 else 'StarNet',executable=self.executable.text())
            self.launch(None,None,options)
        except Exception as exc: self.show_problem('Cannot solve sky position',str(exc))

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
        toggle.toggled.connect(changed)
        layout.addWidget(toggle,alignment=Qt.AlignmentFlag.AlignLeft);layout.addWidget(content)
        return toggle

    def zoom_percent(self):
        # Keep the existing project/export contract while presenting direct scale.
        return round((self.zoom.value()-1)*100,1)

    def refresh_project(self):
        folder=Path(self.output.text()).expanduser().resolve()
        saved=any((folder/name).is_file() for name in ('project.json','scene.json','scene_iterative.json','preview.html'))
        self.project_title.setText(folder.name if saved else Path(self.image_filename() or ('Unsaved image' if self.siril else 'No image selected')).name)
        self.project_title.setToolTip(str(folder))
        ready=(folder/'scene_iterative.json').is_file()
        new_hint=('Current Siril image · uses current pixels. For a linear image, choose autostretch in Advanced settings.' if self.siril else
            ('File image · uses already-stretched pixels.' if self.file_source else 'Open a finished image, or return to a saved project.'))
        self.project_hint.setText(('Saved image · ready to render; analysis is reused.' if ready else 'Saved image · missing preparation steps will resume.') if saved else new_hint)
        self.project_hint.setToolTip(str(folder))
        self.preparation.setEnabled(not saved or read_project(folder).get('stage')=='solved')
        self.start.setText(('Render flight' if ready else 'Resume and render') if saved else 'Prepare and render')
        if folder!=self.prepared:
            self.render_succeeded=False;self.progress_bar.hide();self.render_counter.hide()
            self.result=None;self.result_stem=None
            self.preview.setEnabled(False);self.video.setEnabled(False)
        self.status.setText('Ready to render from the saved project.' if saved else ('Ready to prepare this image.' if self.siril or self.file_source else 'Open an image or project to begin.'))
        file_selected=bool(not self.siril and self.file_source and not saved)
        missing=bool(file_selected and not self.file_source.has_coordinates)
        embedded=bool(file_selected and self.file_source.has_coordinates and self.file_source.wcs_path is None)
        self.coordinates.setVisible(missing)
        self.solver_settings.setVisible(missing)
        self.solve_button.setEnabled(missing)
        if embedded:
            kind='FITS' if self.file_source.is_fits else ('JPEG EXIF' if self.file_source.path.suffix.lower() in {'.jpg','.jpeg'} else 'Astro-TIFF')
            self.project_hint.setText(kind+' · sky coordinates and available observation date read from the image.')
        if missing:
            self.coordinates_hint.setText('Sky position is not saved in this image.\nSolve it with ASTAP to prepare your flight.')
            self.status.setText('Solve sky position above. ASTAP settings are under Advanced settings.')
        self.start.setEnabled((saved or bool(self.siril or self.file_source)) and not missing)

    def new_from_siril(self):
        name=Path(self.image_filename() or 'image').stem
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
        self.prepared=None;self.output.setText(str(folder));self.refresh_project();self.detect_siril_date()
        self.advanced_toggle.setChecked(True)

    def append_log(self,message,detail=False):
        # Capture full diagnostics even while Details is collapsed.
        self.log.appendPlainText(f'[{datetime.now():%H:%M:%S}] {message}')

    def report_progress(self,message,detail=False):
        self.append_log(message,detail)
        if not detail:
            self.status.setToolTip(message)
            self.status.setText(message if len(message)<160 else message[:157]+'…')

    @staticmethod
    def elapsed_text(seconds):
        seconds=max(0,int(seconds));minutes,seconds=divmod(seconds,60)
        hours,minutes=divmod(minutes,60)
        return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'

    def show_stage_progress(self,label,done,total,elapsed):
        if self.worker and self.worker.cancel.is_set(): return
        self.status.setText(label+'…');self.status.setToolTip(label)
        self.progress_bar.show()
        if total<0:
            self.progress_bar.setRange(0,0);self.progress_bar.setTextVisible(False)
            self.render_counter.clear();self.render_counter.hide();return
        done=max(0,min(done,total))
        self.progress_bar.setRange(0,1000)
        self.progress_bar.setValue(1000 if total==0 else done*1000//total)
        self.progress_bar.setTextVisible(True)
        self.render_counter.setText(self.progress_counter(done,total,elapsed))
        self.render_counter.show()

    def progress_counter(self,done,total,elapsed,prefix=''):
        counter=f'{prefix}{done:,} / {total:,} · elapsed {self.elapsed_text(elapsed)}'
        if done>0 and done<total and elapsed>=2:
            counter+=f' · about {self.elapsed_text(math.ceil(elapsed*(total-done)/done))} remaining'
        return counter

    def show_frame_progress(self,done,total,elapsed):
        if total<=0: return
        self.progress_bar.setRange(0,1000)
        # Frame submission can finish before FFmpeg flushes its output.
        self.progress_bar.setValue(min(999,done*1000//total))
        self.progress_bar.setTextVisible(True);self.progress_bar.show()
        self.render_counter.setText(self.progress_counter(done,total,elapsed,'Frames '));self.render_counter.show()
        if not self.worker or not self.worker.cancel.is_set():
            self.status.setText('Finalizing MP4…' if done==total else 'Rendering video…')

    def show_problem(self,title,message):
        self.status.setText(message)
        self.advanced_toggle.setChecked(True)
        QMessageBox.warning(self,title,message)

    def path_row(self,field,directory):
        host=QWidget();host.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        row=QHBoxLayout(host);row.setContentsMargins(0,0,0,0)
        field.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        row.addWidget(field,1);button=QPushButton('Browse…')
        button.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed);row.addWidget(button)
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
            if self.siril:
                with self.siril.image_lock():
                    source=self.image_filename() or 'unsaved'
                    header=parse_header(self.siril.get_image_fits_header(),require_solution=False)
                    pixels=self.siril.get_image_pixeldata(preview=self.stretch.currentIndex()==1,linked=True)
                    if pixels is None: raise ValueError('No image is loaded.')
                    pixels=normalized_pixels(pixels).copy()
            else:
                if not self.file_source: raise ValueError('Open an image or project first.')
                source=str(self.file_source.path)
                pixels,header=self.file_source.snapshot()
            if not has_solution(header):
                raise ValueError(UNSOLVED_MESSAGE)
            info=self.selected_date_info()
            if self.epoch.text().strip() and not info: raise ValueError('Enter a valid capture year or date.')
            if not info: info=infer_photo_date(source,header)
            date=info['value'] if info else None
            if not date:
                self.advanced_toggle.setChecked(True);self.epoch.setFocus()
                raise ValueError('Enter the observation date in Advanced settings; this image has no DATE-OBS.')
            Time(date)
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom_percent(),max_stars=self.star_limit.value(),mode="iterative",
                engine='StarXTerminator' if self.engine.currentIndex()==0 else 'StarNet',
                executable=str(Path(self.executable.text()).resolve()),ffmpeg=str(Path(self.ffmpeg.text()).resolve()),
                epoch=str(date),date_info=info,output=str(out),source=source)
            self.launch(pixels,header,options)
        except Exception as exc: self.show_problem('Cannot render flight',str(exc))
    def launch(self,pixels,header,options):
            self.prepared=Path(options.output).expanduser().resolve()
            self.result=None;self.preview.setEnabled(False);self.video.setEnabled(False)
            self.start.setEnabled(False);self.advanced_toggle.setEnabled(False);self.cancel_button.setEnabled(True);self.cancel_button.show()
            self.advanced_dialog.close();self.start.setText('Solving…' if getattr(options,'solve',False) else 'Processing…')
            self.render_succeeded=False;self.render_counter.clear();self.render_counter.hide()
            self.progress_bar.setRange(0,0);self.progress_bar.setTextVisible(False)
            self.progress_bar.show();self.status.setText('Starting…')
            self.load_scene.setEnabled(False)
            for control in self.settings: control.setEnabled(False)
            self.append_log('Outputs: '+str(self.prepared))
            self.worker=Worker(pixels,header,options)
            self.worker.progress.connect(self.report_progress)
            self.worker.frame_progress.connect(self.show_frame_progress)
            self.worker.stage_progress.connect(self.show_stage_progress)
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
            if read_project(self.prepared).get('stage')=='solved':
                if not Path(self.executable.text()).is_file() or not os.access(self.executable.text(),os.X_OK):
                    raise ValueError('Choose the star-removal executable in Advanced settings before preparing the project.')
                date=self.epoch.text().strip() or read_project(self.prepared).get('epoch','')
                if not date: raise ValueError('Enter the observation date in Advanced settings before preparing the project.')
                if not self.selected_date_info(): raise ValueError('Enter a valid capture year or date.')
            selected=self.selected_date_info()
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom_percent(),max_stars=self.star_limit.value(),mode="iterative",
                output=str(self.prepared),ffmpeg=self.ffmpeg.text(),reuse=True,
                engine='StarXTerminator' if self.engine.currentIndex()==0 else 'StarNet',
                executable=self.executable.text(),epoch=selected['value'] if selected else '',date_info=selected)
            self.launch(None,None,options)
        except Exception as exc: self.show_problem('Cannot render flight',str(exc))
    def load_prepared(self):
        selected=QFileDialog.getExistingDirectory(self,'Choose a SPACER project or an older prepared run folder',self.preferences.directory('project_directory'))
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
            self.star_limit.setValue(state.get('max_stars',DEFAULT_MAX_STARS))
            if state.get('ffmpeg'): self.ffmpeg.setText(state['ffmpeg'])
            if state.get('stage')=='solved':
                self.engine.setCurrentIndex(0 if state.get('engine')=='StarXTerminator' else 1)
                self.executable.setText(state.get('executable',''))
            saved_date=state.get('date_info') or saved_scene.get('date_info') or date_info(state.get('epoch',''),'Saved project date (source unrecorded)',True)
            if not saved_date and state.get('stage')=='solved' and (folder/'source_wcs.fits').is_file():
                from astropy.io import fits
                original=Path(state.get('source') or folder/'source_wcs.fits')
                if not original.is_file(): original=folder/'source_wcs.fits'
                saved_date=infer_photo_date(original,fits.getheader(folder/'source_wcs.fits'))
            self.set_date_info(saved_date)
            solver=state.get('astrometry',{})
            if solver.get('executable'): self.astap.setText(solver['executable'])
            if solver.get('database'): self.database.setText(solver['database'])
        self.result_stem=state.get('last_render')
        self.result=folder if self.result_stem else None
        self.preview.setEnabled(bool(self.result and (folder/(self.result_stem+'.html')).exists()))
        self.video.setEnabled(bool(self.result and (folder/(self.result_stem+'.mp4')).exists()))
        if folder!=self.prepared:
            self.render_succeeded=False;self.progress_bar.hide();self.render_counter.hide()
        self.prepared=folder;self.output.setText(str(folder));self.refresh_project()
        self.remember_project(folder)
        self.append_log(f'Tool v{VERSION} · saved field {field_description(saved_scene)}\nReusing saved image and Gaia field: '+str(folder)+
            '\nSaved image and preparation settings are used for this project.')
    def cancel(self):
        if self.worker:
            self.worker.cancel.set();self.cancel_button.setEnabled(False)
            self.report_progress('Cancelling… Waiting for the current operation to stop. Completed catalogue regions are kept.')
    def completed(self,path):
        if getattr(self.worker.options,'solve',False):
            self.use_prepared(Path(path))
            self.report_progress('Sky position solved. The matching date is filled automatically; you can review it in Advanced settings.')
            return
        self.render_succeeded=True
        self.progress_bar.setRange(0,1000);self.progress_bar.setValue(1000);self.progress_bar.setTextVisible(True)
        self.result=Path(path);self.result_stem=self.worker.options.result_stem
        self.report_progress('Flight ready. Open the preview or video.');self.append_log(str(self.result/(self.result_stem+'.mp4')))
        self.preview.setEnabled(True);self.video.setEnabled(True)
    def failed(self,message):
        if self.worker and self.worker.cancel.is_set():
            self.report_progress('Cancelled. Saved preparation and earlier exports are kept.');return
        self.report_progress(message);self.details_toggle.setChecked(True)
        QMessageBox.warning(self,'Flight not completed',message)
    def finished(self):
        self.start.setEnabled(True);self.advanced_toggle.setEnabled(True);self.cancel_button.setEnabled(False)
        self.cancel_button.hide()
        if not self.render_succeeded:
            self.progress_bar.hide();self.render_counter.hide()
        self.load_scene.setEnabled(True)
        for control in self.settings: control.setEnabled(True)
        if self.prepared and (self.prepared/'project.json').is_file(): self.remember_project(self.prepared)
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

