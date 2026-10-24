"""Shared SPACER desktop interface; Siril is an optional image source."""
import sys
import math
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import threading
import traceback

from motion import validate_motion
from version import VERSION, field_description
from preferences import Preferences
from photo_date import infer_photo_date, date_info
from siril_pipeline import normalized_pixels, parse_header, has_solution, find_tool, run_pipeline, render_prepared, load_prepared_scene, read_project, resume_project, calculation_folder, recalculation_missing, recalculate_project, UNSOLVED_MESSAGE
from astropy.time import Time
from image_source import FileImageSource
from astap_solver import solve_project, find_astap, resolve_astap
from astro_platesolve import SolveOptions, validate_backend
from task_progress import Diagnostic
from density import DEFAULT_MAX_STARS, MAX_MOVING_STARS
from PyQt6.QtCore import QThread, pyqtSignal, QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication,QWidget,QVBoxLayout,QFormLayout,QHBoxLayout,
    QLabel,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QPushButton,QFileDialog,
    QMessageBox,QPlainTextEdit,QGroupBox,QToolButton,QProgressBar,QSizePolicy,QDialog,QDialogButtonBox,QScrollArea,QCheckBox)


class ZoomSpinBox(QDoubleSpinBox):
    """Show a direct scale without trailing zeroes, using the system locale."""
    def textFromValue(self,value):
        return self.locale().toString(value,'f',3).rstrip('0').rstrip(self.locale().decimalPoint())


class TargetWorker(QThread):
    completed=pyqtSignal(object)
    failed=pyqtSignal(str)
    def __init__(self,header):
        super().__init__();self.header=header
    def run(self):
        try:
            from targets import find_targets
            self.completed.emit(find_targets(self.header))
        except Exception as exc:self.failed.emit(str(exc))


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
            elif getattr(self.options,'recalculate',False):
                out=recalculate_project(self.options.output,self.options,self.report,self.cancel)
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
        self.target_worker=None;self.target_info=None
        self.prepared_star_limit=None;self.prepared_star_count=None;self.prepared_approximate=None
        self.render_succeeded=False
        self.setWindowTitle(f'SPACER — v{VERSION}')
        self.resize(680,560)
        self.setMinimumWidth(600)
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        self.main_scroll=QScrollArea();self.main_scroll.setWidgetResizable(True);self.main_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.main_content=QWidget();self.main_scroll.setWidget(self.main_content);outer.addWidget(self.main_scroll)
        layout=QVBoxLayout(self.main_content);layout.setContentsMargins(24,20,24,20);layout.setSpacing(16)
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
        self.flight_form=form
        form.setContentsMargins(16,16,16,16);form.setVerticalSpacing(12)
        self.seconds=QSpinBox();self.seconds.setRange(4,600);self.seconds.setValue(60)
        self.seconds.setSuffix(' s');form.addRow('Duration',self.seconds)
        self.zoom_mode=QComboBox()
        self.zoom_mode.addItem('Camera zoom','independent')
        self.zoom_mode.addItem('Travel toward a target','target_distance')
        form.addRow('Motion',self.zoom_mode)
        self.zoom=ZoomSpinBox();self.zoom.setDecimals(3);self.zoom.setRange(1,101)
        self.zoom.setSingleStep(.1);self.zoom.setValue(1.3);self.zoom.setSuffix('×')
        form.addRow('Final zoom',self.zoom)
        self.target_row=QWidget();target_layout=QHBoxLayout(self.target_row)
        target_layout.setContentsMargins(0,0,0,0)
        self.target_summary=QLabel('No target selected');self.target_summary.setWordWrap(True)
        self.find_targets_button=QPushButton('Choose target…')
        self.find_targets_button.setToolTip('Find familiar objects using the solved sky position. Manual distance is available in Advanced settings.')
        self.find_targets_button.clicked.connect(self.lookup_targets)
        target_layout.addWidget(self.target_summary,1);target_layout.addWidget(self.find_targets_button)
        form.addRow('Target',self.target_row)
        self.perspective_note=QLabel();self.perspective_note.setWordWrap(True);form.addRow(self.perspective_note)
        layout.addWidget(self.flight_group)

        self.advanced=QWidget();advanced_layout=QFormLayout(self.advanced)
        advanced_layout.setContentsMargins(0,8,0,0);advanced_layout.setVerticalSpacing(10)
        self.motion_settings=QGroupBox('Motion details');motion_form=QFormLayout(self.motion_settings)
        motion_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.travel_pc=QDoubleSpinBox();self.travel_pc.setRange(0,1e12);self.travel_pc.setDecimals(3);self.travel_pc.setValue(80);self.travel_pc.setSuffix(' pc')
        self.travel_pc.setToolTip('Forward travel controls the parallax of moving stars in either motion style.')
        motion_form.addRow('Travel distance',self.travel_pc)
        self.target_distance_pc=QDoubleSpinBox();self.target_distance_pc.setRange(0,1e12);self.target_distance_pc.setDecimals(3);self.target_distance_pc.setValue(0)
        self.target_distance_pc.setSpecialValueText('Choose a target or enter distance');self.target_distance_pc.setSuffix(' pc')
        motion_form.addRow('Manual target distance',self.target_distance_pc)
        self.target_distance_pc.setToolTip('Approximate distance of the flat background plane. Must exceed travel distance. Editing clears catalogue attribution.')
        self.target_origin=QLabel('No target distance selected');self.target_origin.setWordWrap(True)
        self.target_origin.setFixedHeight(self.target_origin.fontMetrics().lineSpacing()*2+4)
        motion_form.addRow(self.target_origin)
        self.motion_settings.setToolTip('Exports use 24 fps, up to 1920 px wide, with 1.5-second easing at either end.')
        advanced_layout.addRow(self.motion_settings)
        self.target_distance_pc.valueChanged.connect(self.clear_target_origin)
        self.zoom_mode.currentIndexChanged.connect(self.refresh_motion_ui)
        self.travel_pc.valueChanged.connect(self.refresh_motion_ui)
        self.target_distance_pc.valueChanged.connect(self.refresh_motion_ui)
        self.refresh_motion_ui()

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
        self.executable.setToolTip('Used to create the starless image. Changing its path does not alter saved star-removal output.')
        self.engine.currentIndexChanged.connect(self.choose_engine);self.choose_engine()
        if not self.executable.text() and find_tool('starnet2'): self.engine.setCurrentIndex(1)
        self.epoch=QLineEdit();self.epoch.setPlaceholderText('Automatic; override with YYYY or YYYY-MM-DD')
        prep.addRow('Observation date',self.epoch)
        self.date_origin=QLabel('Capture metadata is preferred; file dates are used as estimates.');self.date_origin.setWordWrap(True)
        self.date_origin.setFixedHeight(self.date_origin.fontMetrics().lineSpacing()*2+4)
        prep.addRow(self.date_origin)
        self.epoch.textEdited.connect(self.update_date_origin)
        date_hint=QLabel('Approximate capture year is enough for ordinary matching. You can correct the detected date or enter just a year.')
        self.epoch.setToolTip(date_hint.text())
        self.epoch.setToolTip('Gaia positions are corrected for stellar proper motion at this date. A nearby estimate is better than an unrelated date.')
        self.new_preparation_note=('Uses a copy of the current Siril pixels.' if siril else 'Uses file pixels. Supply an already-stretched image.')+' First preparation needs internet for Gaia.\nIterative separation is experimental; ambiguous star groups remain flat.'
        self.preparation_note=QLabel(self.new_preparation_note)
        self.preparation_note.setWordWrap(True);self.preparation_note.setFixedHeight(self.preparation_note.fontMetrics().lineSpacing()*3+4)
        prep.addRow(self.preparation_note);advanced_layout.addRow(self.preparation)
        self.calculation_settings=QGroupBox('Star calculations');calculation_form=QFormLayout(self.calculation_settings)
        calculation_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.star_limit=QSpinBox();self.star_limit.setRange(100,MAX_MOVING_STARS);self.star_limit.setSingleStep(1000);self.star_limit.setValue(DEFAULT_MAX_STARS)
        self.star_limit.setToolTip('Fewer moving stars make preparation and rendering faster. Unselected stars stay in the photograph. Use Recalculate stars to fit additional stars from the saved image layers.')
        calculation_form.addRow('Moving stars (maximum)',self.star_limit)
        self.approximate_distances=QCheckBox('Include approximate distances')
        self.approximate_distances.setToolTip('Add photogeometric estimates (up to 50% fractional interval) and screened Hipparcos-2 parallaxes. First use needs internet. Recalculate stars to update a saved project.')
        self.approximate_distances.toggled.connect(self.update_calculation_hint)
        self.recalculation=QWidget();recalculation_layout=QVBoxLayout(self.recalculation)
        recalculation_layout.setContentsMargins(0,0,0,0)
        self.calculation_hint=QLabel();self.calculation_hint.setWordWrap(True)
        self.calculation_hint.setFixedHeight(self.calculation_hint.fontMetrics().lineSpacing()*3+4)
        recalculation_layout.addWidget(self.calculation_hint)
        self.recalculate_button=QPushButton('Recalculate stars');self.recalculate_button.setAutoDefault(False)
        self.recalculate_button.clicked.connect(self.recalculate_stars)
        calculation_actions=QHBoxLayout()
        calculation_actions.addWidget(self.recalculate_button)
        calculation_actions.addWidget(self.approximate_distances)
        calculation_actions.addStretch()
        recalculation_layout.addLayout(calculation_actions)
        calculation_form.addRow(self.recalculation);advanced_layout.addRow(self.calculation_settings)
        self.star_limit.valueChanged.connect(self.update_calculation_hint)
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
            selected=QFileDialog.getExistingDirectory(self,'Choose ASTAP star database folder',self.picker_directory(self.database.text()))
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
        self.export_settings=QGroupBox('Output and tools');export_form=QFormLayout(self.export_settings)
        export_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.ffmpeg=QLineEdit(find_tool('ffmpeg'));export_form.addRow('FFmpeg',self.path_row(self.ffmpeg,False))
        name=self.image_filename() or 'image'
        self.output=QLineEdit(str(Path(name).expanduser().resolve().parent/'flythrough'/Path(name).stem))
        self.output.setPlaceholderText('Choose a project folder')
        export_form.addRow('Project folder',self.path_row(self.output,True));advanced_layout.addRow(self.export_settings)
        self.advanced_toggle=self.disclosure(layout,'Advanced settings',self.advanced)

        self.activity=QWidget();activity_layout=QVBoxLayout(self.activity)
        activity_layout.setContentsMargins(0,0,0,0);activity_layout.setSpacing(4)
        layout.addWidget(self.activity)
        self.status=QLabel('Ready to prepare this image.');self.status.setWordWrap(True)
        self.status.setFixedHeight(self.status.fontMetrics().lineSpacing()*2+8)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        activity_layout.addWidget(self.status)
        self.progress_bar=QProgressBar();self.progress_bar.setRange(0,0);self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(18);self.progress_bar.hide();activity_layout.addWidget(self.progress_bar)
        self.render_counter=QLabel();self.render_counter.setWordWrap(True);self.render_counter.hide();activity_layout.addWidget(self.render_counter)
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
        if self.image_filename() and Path(self.output.text()).is_dir() and any(Path(self.output.text()).iterdir()):
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
        self.file_source=source;self.prepared=None;self.reset_target_distance();self.target.clear();self.set_date_info(source.date_info())
        self.star_limit.setValue(DEFAULT_MAX_STARS)
        self.approximate_distances.setChecked(False)
        self.prepared_star_limit=None;self.prepared_star_count=None;self.prepared_approximate=None
        self.output.setText(str(source.path.parent/'flythrough'/source.path.stem))
        self.refresh_project()
        self.remember_image()
        if Path(self.output.text()).is_dir() and any(Path(self.output.text()).iterdir()): self.use_prepared(Path(self.output.text()))

    def refresh_motion_ui(self,*_):
        physical=self.zoom_mode.currentData()=='target_distance'
        self.flight_form.setRowVisible(self.zoom,not physical)
        self.zoom.setEnabled(not physical)
        self.flight_form.setRowVisible(self.target_row,physical)
        self.flight_form.setRowVisible(self.perspective_note,physical)
        self.target_distance_pc.setEnabled(physical)
        d,s=self.target_distance_pc.value(),self.travel_pc.value()
        from targets import approximate_distance_label
        if d:
            name=self.target_info['name'] if self.target_info else 'Manual distance'
            self.target_summary.setText(f'{name} · {approximate_distance_label(d)}')
        else:self.target_summary.setText('No target selected')
        self.target_summary.setToolTip(self.target_origin.text())
        self.perspective_note.setText('Choose a target, or enter a distance in Advanced settings.' if not d else (
            ('Very little background zoom at this distance.' if d/(d-s)<1.005 else f'Final enlargement: {d/(d-s):.3g}×') if d>s else 'Reduce travel distance in Advanced settings; it must be less than the target distance.'))
        if hasattr(self,'start'):self.fit_main_window()

    def reset_target_distance(self):
        self.target_distance_pc.setValue(0)
        self.clear_target_origin()
        self.target_origin.setText('No target distance selected for this image')

    def clear_target_origin(self,*_):
        self.target_info=None
        self.target_origin.setText('Manual target distance')
        self.refresh_motion_ui()

    def target_header(self):
        from astropy.io import fits
        if self.prepared and (self.prepared/'source_wcs.fits').exists():
            return fits.getheader(self.prepared/'source_wcs.fits')
        if self.siril:return parse_header(self.siril.get_image_fits_header())
        if self.file_source:return self.file_source.header()
        raise ValueError('Open a plate-solved image or saved project first.')

    def lookup_targets(self):
        try:
            if self.worker and self.worker.isRunning():raise ValueError('Wait for processing to finish.')
            header=self.target_header()
            from targets import field_query
            query,*_=field_query(header)
            self.target_lookup_query=query
            self.target_worker=TargetWorker(header)
            self.find_targets_button.setEnabled(False);self.find_targets_button.setText('Looking up SIMBAD…')
            self.target_worker.completed.connect(self.show_targets)
            self.target_worker.failed.connect(lambda message:self.show_problem('Target lookup failed',message))
            self.target_worker.finished.connect(self.target_lookup_finished)
            self.target_worker.start()
        except Exception as exc:self.show_problem('Cannot find targets',str(exc))

    def target_lookup_finished(self):
        self.find_targets_button.setText('Choose target…');self.find_targets_button.setEnabled(True)

    def show_targets(self,rows):
        from targets import field_query
        try:
            if field_query(self.target_header())[0]!=self.target_lookup_query:
                self.show_problem('Field changed','The image changed during lookup. Find targets again.');return
        except Exception:return
        if not rows:
            self.show_problem('No catalogue targets','No familiar deep-sky catalogue targets were found in this frame. You can enter a distance manually.');return
        from targets import approximate_targets, approximate_distance_label
        rows=approximate_targets(rows)
        dialog=QDialog(self);dialog.setWindowTitle('Choose a target')
        layout=QVBoxLayout(dialog)
        note=QLabel('Choose the object you want to travel toward.')
        note.setWordWrap(True);layout.addWidget(note)
        choice=QComboBox()
        for row in rows:
            distance=approximate_distance_label(row['distance_pc'])
            choice.addItem(f"{row['name']} · {distance}",row)
        layout.addWidget(choice)
        details=QLabel();details.setWordWrap(True);layout.addWidget(details)
        def update_details():
            row=choice.currentData()
            details.setText('Approximate distance. You can adjust it in Advanced settings.' if row['distance_pc'] else 'No distance available. Enter one in Advanced settings.')
            details.setToolTip(row['distance_summary'])
        choice.currentIndexChanged.connect(update_details);update_details()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.resize(680,260)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        row=choice.currentData()
        if row['distance_pc'] is None:
            self.reset_target_distance();self.target_origin.setText(row['name']+': no published distance here; enter manually.');return
        if not self.target_distance_pc.minimum()<=row['distance_pc']<=self.target_distance_pc.maximum():
            self.show_problem('Distance outside supported range','Enter a target distance within the supported range manually.');return
        self.target_distance_pc.setValue(row['distance_pc'])
        self.target_info=dict(row,selected_at=datetime.now().astimezone().isoformat())
        self.target_origin.setText(f"{row['name']} · approximate SIMBAD distance")
        self.zoom_mode.setCurrentIndex(self.zoom_mode.findData('target_distance'))
        self.refresh_motion_ui()

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
            suffix=' You can override it.' if self.preparation.isEnabled() else ' Saved matching date.'
            self.date_origin.setText(prefix+info['source']+'.'+suffix)
        else: self.date_origin.setText('No usable date found. Enter an approximate capture year.' if self.preparation.isEnabled() else 'Saved matching date is not recorded.')

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
            validate_backend(SolveOptions(executable=self.astap.text()))
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
            dialog=QDialog(self);dialog.setWindowTitle('Advanced settings');dialog.resize(760,600)
            body=QVBoxLayout(dialog)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(content);content.show();body.addWidget(scroll)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.close);body.addWidget(buttons)
            self.advanced_scroll=scroll
            toggle.toggled.connect(self.show_advanced)
            dialog.finished.connect(lambda _: toggle.setChecked(False))
            self.advanced_dialog=dialog
            layout.addWidget(toggle)
            return toggle
        def changed(opened):
            content.setVisible(opened)
            toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
            self.fit_main_window()
        toggle.toggled.connect(changed)
        layout.addWidget(toggle,alignment=Qt.AlignmentFlag.AlignLeft);layout.addWidget(content)
        return toggle

    def fit_main_window(self):
        form=self.main_content.layout()
        height=form.totalHeightForWidth(self.width()) if form.hasHeightForWidth() else form.sizeHint().height()
        self.resize(self.width(),min(height+2,self.screen().availableGeometry().height()-64))

    def show_advanced(self,opened):
        dialog=self.advanced_dialog
        if not opened: dialog.hide();return
        available=self.screen().availableGeometry()
        width=min(max(760,dialog.width()),available.width()-48)
        self.advanced.ensurePolished()
        content_width=width-dialog.layout().contentsMargins().left()-dialog.layout().contentsMargins().right()-4
        form=self.advanced.layout()
        content_height=form.totalHeightForWidth(content_width) if form.hasHeightForWidth() else form.sizeHint().height()
        margins=dialog.layout().contentsMargins()
        chrome=margins.top()+margins.bottom()+dialog.layout().spacing()+dialog.findChild(QDialogButtonBox).sizeHint().height()+8
        dialog.resize(width,min(content_height+chrome,available.height()-64))
        dialog.show();dialog.raise_();dialog.activateWindow()

    def zoom_percent(self):
        # Keep the existing project/export contract while presenting direct scale.
        return round((self.zoom.value()-1)*100,1)

    def refresh_project(self):
        folder=Path(self.output.text()).expanduser().resolve()
        saved=any((folder/name).is_file() for name in ('project.json','scene.json','scene_iterative.json','preview.html'))
        self.project_title.setText(folder.name if saved else Path(self.image_filename() or ('Unsaved image' if self.siril else 'No image selected')).name)
        self.project_title.setToolTip(str(folder))
        calculation_error=None
        try: ready=(calculation_folder(folder)/'scene_iterative.json').is_file()
        except ValueError as exc: ready=False;calculation_error=str(exc)
        new_hint=('Uses the current Siril image.' if self.siril else
            ('Ready to prepare.' if self.file_source else 'Use a finished, stretched image.'))
        self.project_hint.setText('Uses the saved project image.' if saved else new_hint)
        self.project_hint.setToolTip(str(folder))
        self.preparation.setEnabled(not saved or read_project(folder).get('stage')=='solved')
        self.update_date_origin()
        self.preparation_note.setText(self.new_preparation_note if not saved or read_project(folder).get('stage')=='solved' else
            'Uses the saved image and preparation settings. Completed star-removal output is reused.\nChanging an engine path does not change saved starless layers or prepared stars.')
        self.update_calculation_hint()
        self.start.setText(('Render flight' if ready else 'Resume and render') if saved else 'Prepare and render')
        if folder!=self.prepared:
            self.render_succeeded=False;self.progress_bar.hide();self.render_counter.hide()
            self.result=None;self.result_stem=None
            self.preview.setEnabled(False);self.video.setEnabled(False)
        self.status.setText(('Ready to render from the saved project.' if ready else 'Ready to resume preparation.') if saved else ('Ready to prepare this image.' if self.siril or self.file_source else 'Open an image or project to begin.'))
        file_selected=bool(not self.siril and self.file_source and not saved)
        missing=bool(file_selected and not self.file_source.has_coordinates)
        embedded=bool(file_selected and self.file_source.has_coordinates and self.file_source.wcs_path is None)
        self.coordinates.setVisible(missing)
        self.solver_settings.setVisible(missing)
        self.solve_button.setEnabled(missing)
        if embedded:
            kind='FITS' if self.file_source.is_fits else ('JPEG EXIF' if self.file_source.path.suffix.lower() in {'.jpg','.jpeg'} else 'Astro-TIFF')
            self.project_hint.setText('Sky position available.')
            self.project_hint.setToolTip(kind+' · sky coordinates and available observation date read from the image.\n'+str(folder))
        if missing:
            self.coordinates_hint.setText('Sky position is not saved in this image.\nSolve it with ASTAP to prepare your flight.')
            self.status.setText('Solve sky position above. ASTAP settings are under Advanced settings.')
        self.start.setEnabled((saved or bool(self.siril or self.file_source)) and not missing)
        if calculation_error:
            self.project_hint.setText('Saved image · star calculations need rebuilding.')
            self.status.setText(calculation_error);self.start.setEnabled(False)
        self.fit_main_window()

    def update_calculation_hint(self,*_):
        if not hasattr(self,'output'): return
        folder=Path(self.output.text()).expanduser().resolve()
        missing=recalculation_missing(folder)
        self.recalculate_button.setEnabled(not missing)
        saved=any((folder/name).is_file() for name in ('project.json','scene.json','scene_iterative.json','preview.html'))
        if not saved and missing:
            self.calculation_hint.setText('Available after first preparation. Recalculate stars reuses the saved image, starless layer and Gaia catalogue.')
        elif missing:
            self.calculation_hint.setText('Recalculation needs saved layers: '+', '.join(missing)+'.')
        else:
            summary=('Distance coverage changed; recalculate to apply it. ' if self.prepared_approximate is not None and self.approximate_distances.isChecked()!=self.prepared_approximate else '')
            summary+=(f'Prepared: {self.prepared_star_count:,} moving stars. ' if folder==self.prepared and self.prepared_star_count is not None else '')
            if folder==self.prepared and self.prepared_star_limit is not None and self.star_limit.value()>self.prepared_star_limit:
                summary+='Recalculate to apply the higher limit. '
            self.calculation_hint.setText(summary+'Reuses saved layers and catalogue caches. Keeps previous calculations and exports.')

    def recalculate_stars(self):
        try:
            folder=Path(self.output.text()).expanduser().resolve()
            missing=recalculation_missing(folder)
            if missing: raise ValueError('Recalculation needs saved project files: '+', '.join(missing))
            options=SimpleNamespace(output=str(folder),recalculate=True,max_stars=self.star_limit.value(),approximate_distances=self.approximate_distances.isChecked())
            self.launch(None,None,options)
        except Exception as exc: self.show_problem('Cannot recalculate stars',str(exc))

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
        self.prepared=None;self.reset_target_distance();self.output.setText(str(folder));self.refresh_project();self.detect_siril_date()
        self.star_limit.setValue(DEFAULT_MAX_STARS)
        self.approximate_distances.setChecked(False)
        self.prepared_star_limit=None;self.prepared_star_count=None;self.prepared_approximate=None
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
                selected=QFileDialog.getExistingDirectory(self,'Choose a project folder',self.picker_directory(field.text()))
                if selected:
                    folder=Path(selected)
                    if any((folder/name).is_file() for name in ('project.json','scene.json','preview.html','scene_iterative.json')):
                        try: self.use_prepared(folder)
                        except Exception as exc: QMessageBox.warning(self,'Prepared field missing',str(exc))
                    else:
                        field.setText(str(folder));self.refresh_project()
            else:
                selected,_=QFileDialog.getOpenFileName(self,'Choose executable',self.picker_directory(field.text()))
                if selected: field.setText(selected)
        button.clicked.connect(browse)
        return host

    def picker_directory(self,value):
        """Start at the current path, or its nearest existing parent."""
        if value.strip():
            path=Path(value).expanduser().resolve()
            while not path.is_dir() and path!=path.parent: path=path.parent
            return str(path)
        source=self.image_filename()
        if source: return str(Path(source).expanduser().resolve().parent)
        return self.preferences.directory('project_directory')
    def choose_engine(self,*_):
        self.executable.setText(find_tool('rc-astro' if self.engine.currentIndex()==0 else 'starnet2'))
    def begin(self):
        try:
            import os
            if not self.output.text().strip(): raise ValueError('Choose a project folder in Advanced settings.')
            out=Path(self.output.text()).expanduser()
            if out.exists() and any(out.iterdir()):
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
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom_percent(),zoom_mode=self.zoom_mode.currentData(),travel_pc=self.travel_pc.value(),target_distance_pc=self.target_distance_pc.value(),target_info=self.target_info,approximate_distances=self.approximate_distances.isChecked(),max_stars=self.star_limit.value(),mode="iterative",
                engine='StarXTerminator' if self.engine.currentIndex()==0 else 'StarNet',
                executable=str(Path(self.executable.text()).resolve()),ffmpeg=str(Path(self.ffmpeg.text()).resolve()),
                epoch=str(date),date_info=info,output=str(out),source=source)
            self.launch(pixels,header,options)
        except Exception as exc: self.show_problem('Cannot render flight',str(exc))
    def launch(self,pixels,header,options):
            if not getattr(options,'solve',False) and not getattr(options,'recalculate',False):
                validate_motion(getattr(options,'zoom_mode','independent'),getattr(options,'travel_pc',80),getattr(options,'target_distance_pc',400))
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
            options=SimpleNamespace(seconds=self.seconds.value(),zoom=self.zoom_percent(),zoom_mode=self.zoom_mode.currentData(),travel_pc=self.travel_pc.value(),target_distance_pc=self.target_distance_pc.value(),target_info=self.target_info,approximate_distances=self.approximate_distances.isChecked(),max_stars=self.star_limit.value(),mode="iterative",
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
        try: active=calculation_folder(folder)
        except ValueError: active=None  # Keep the cached-layer recalculation action available.
        if active is not None and (active/'scene_iterative.json').exists():
            import json
            saved_scene=json.loads((active/'scene_iterative.json').read_text())
        else:
            saved_scene=load_prepared_scene(folder) if active is not None and ((folder/'scene.json').exists() or (folder/'preview.html').exists()) else {}
        if not saved_scene and not state and not (folder/'scene_iterative.json').exists():
            raise ValueError('This folder is not a SPACER project.')
        if restore:
            self.seconds.setValue(state.get('seconds',60))
            self.zoom.setValue(1+state.get('zoom',30)/100)
            self.travel_pc.setValue(state.get('travel_pc',80))
            self.clear_target_origin()
            self.target_distance_pc.setValue(state.get('target_distance_pc',0))
            self.target_info=state.get('target_info')
            # Discard catalogue selections inherited from a different field.
            if self.target_info and all(key in self.target_info for key in ('ra_deg','dec_deg')) and (folder/'source_wcs.fits').is_file():
                from astropy.io import fits
                from targets import in_field
                from astropy.wcs import WCS
                target_header=fits.getheader(folder/'source_wcs.fits')
                if not in_field(WCS(target_header,naxis=2).celestial,target_header['NAXIS1'],target_header['NAXIS2'],self.target_info['ra_deg'],self.target_info['dec_deg']):
                    self.reset_target_distance()
            if self.target_info:self.target_origin.setText(f"{self.target_info['name']} · SIMBAD distance" + (" (approximate)" if self.target_info.get("approximate") else ""))
            self.zoom_mode.setCurrentIndex(max(0,self.zoom_mode.findData(state.get('zoom_mode','independent'))))
            self.star_limit.setValue(state.get('max_stars',DEFAULT_MAX_STARS))
            self.approximate_distances.setChecked(state.get('approximate_distances',saved_scene.get('distance_coverage',{}).get('enabled',False)))
            if state.get('ffmpeg'): self.ffmpeg.setText(state['ffmpeg'])
            if 'engine' in state:
                self.engine.setCurrentIndex(0 if state['engine']=='StarXTerminator' else 1)
            if 'executable' in state:
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
        self.refresh_motion_ui()
        self.restore_export_links(folder)
        if folder!=self.prepared:
            self.render_succeeded=False;self.progress_bar.hide();self.render_counter.hide()
        self.prepared_approximate=saved_scene.get('distance_coverage',{}).get('enabled',False) if saved_scene else None
        coverage=saved_scene.get('distance_coverage',{})
        self.calculation_hint.setToolTip('\n'.join(f'{source}: {count:,}' for source,count in coverage.get('by_source',{}).items()))
        self.prepared_star_limit=saved_scene.get('motion_selection',{}).get('limit')
        self.prepared_star_count=len(saved_scene['stars']) if 'stars' in saved_scene else None
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
        if getattr(self.worker.options,'recalculate',False):
            self.use_prepared(Path(path))
            self.render_succeeded=True
            self.progress_bar.setRange(0,1000);self.progress_bar.setValue(1000);self.progress_bar.setTextVisible(True)
            self.report_progress('Star calculations updated. Choose Render flight to create a new video.')
            return
        self.render_succeeded=True
        self.use_prepared(Path(path),restore=False)
        self.progress_bar.setRange(0,1000);self.progress_bar.setValue(1000);self.progress_bar.setTextVisible(True)
        self.result=Path(path);self.result_stem=self.worker.options.result_stem
        self.report_progress('Flight ready. Open the preview or video.');self.append_log(str(self.result/(self.result_stem+'.mp4')))
        self.preview.setEnabled(True);self.video.setEnabled(True)

    def restore_export_links(self,folder):
        self.result_stem=read_project(folder).get('last_render')
        self.result=folder if self.result_stem else None
        self.preview.setEnabled(bool(self.result and (folder/(self.result_stem+'.html')).exists()))
        self.video.setEnabled(bool(self.result and (folder/(self.result_stem+'.mp4')).exists()))
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
        if self.prepared: self.restore_export_links(self.prepared)
        self.status.setText(message)
    def open_result(self,name):
        if self.result:
            suffix='.html' if name=='preview.html' else '.mp4'
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result/(self.result_stem+suffix))))
    def closeEvent(self,event):
        if self.target_worker and self.target_worker.isRunning():
            self.show_problem('Target lookup running','Wait for the catalogue lookup to finish (each network request has a 30-second timeout).');event.ignore();return
        if self.worker and self.worker.isRunning():
            self.report_progress('A flight is still processing. Cancel and wait for it to stop before closing.');event.ignore()
        else: event.accept()

